"""Run real VoltCart code with temporary data and controlled classroom faults.

Run from the project root: python -m labs.langsmith_lab --help
No model API calls are made by this module. --live uploads to LangSmith.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from langsmith import Client, tracing_context

import agent_service
import config
import observability as obs
from agent_service import AgentService
from store import OrderStore

SCENARIOS = ("happy", "threads", "slow", "tool-error", "fallback", "business-denial", "replay", "privacy")
SEARCH = "Recommend headphones under 10000"


def live_client() -> Client:
    if not config.LANGSMITH_ENABLED or not config.LANGSMITH_API_KEY.strip() or config.LANGSMITH_API_KEY.startswith("PASTE_"):
        raise ValueError("Set LANGSMITH_ENABLED=True and LANGSMITH_API_KEY in config.py first.")
    return Client(api_url=config.LANGSMITH_ENDPOINT, api_key=config.LANGSMITH_API_KEY,
                  workspace_id=config.LANGSMITH_WORKSPACE_ID or None, timeout_ms=10000)


def compact(result: dict) -> dict:
    """Only classroom facts needed for assertions; never persist full prompts."""
    entities = result.get("entities", {})
    trace = result.get("trace", {})
    return {
        "mode": result.get("mode"), "has_warning": bool(result.get("warning")),
        "tools": [a["tool"] for a in result.get("actions", [])],
        "tool_denials": sum(a.get("result", {}).get("ok") is False for a in result.get("actions", [])),
        "products": [{"id": p["id"], "price": p["price"]} for p in entities.get("products", [])],
        "order_id": (entities.get("order") or {}).get("id"),
        "local_trace_id": trace.get("id"), "correlation_id": trace.get("correlation_id"),
        "outcome": trace.get("outcome"), "guardrails": trace.get("guardrails", []),
    }


def run_scenario(name: str, *, live: bool = False, batch: str = "offline") -> list[dict]:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {name}")
    records = []
    session = f"lab-{name}-{uuid.uuid4().hex[:10]}"
    # All patches are process-local and restored on exit, including exceptions.
    with tempfile.TemporaryDirectory(prefix="voltcart-lab-") as folder, ExitStack() as stack:
        stack.enter_context(patch.object(config, "LANGSMITH_ENABLED", live))
        stack.enter_context(patch.object(agent_service, "ENABLE_LOCAL_FALLBACK", True))
        if live:
            client = live_client()
            stack.callback(client.close)
            stack.callback(client.flush)
            stack.enter_context(patch.object(obs, "_client", client))
        else:
            client = None
        stack.enter_context(tracing_context(enabled=live, client=client,
                            metadata={"lab": name, "lab_batch": batch, "release": "classroom-v1"}))
        store = OrderStore(Path(folder) / "lab.db")
        agent = AgentService(store)

        if name == "business-denial":
            @obs.observe(name="Lab tool router")
            def denied(message, state):
                result = agent._execute_tool("place_order", {"items": [{"product_id": "AUD-301", "quantity": 1}]})
                return {"mode": "local", "message": result.get("error", ""), "entities": {},
                        "actions": [{"tool": "place_order", "summary": "Injected unauthorized tool call", "result": result}]}
            stack.enter_context(patch.object(agent, "_chat_local", denied))

        if name in {"slow", "tool-error"}:
            original = agent_service.search_products

            @obs.observe("tool", name="Lab catalog lookup")
            def lookup(**kwargs):
                if name == "tool-error":
                    raise RuntimeError("Injected classroom catalog failure")
                time.sleep(1.2)
                return original(**kwargs)

            stack.enter_context(patch.object(agent_service, "search_products", lookup))
        if name == "fallback":
            stack.enter_context(patch.object(agent_service, "openai_is_configured", return_value=True))
            # The decorated Model request still runs, but its HTTP call cannot leave this process.
            stack.enter_context(patch.object(agent_service.urllib.request, "urlopen",
                                            side_effect=TimeoutError("Injected classroom timeout")))
            # A syntactically valid endpoint/key lets request construction reach the mock.
            stack.enter_context(patch.object(agent_service, "OPENAI_BASE_URL", "https://example.test/openai/v1"))
            stack.enter_context(patch.object(agent_service, "OPENAI_API_KEY", "classroom-placeholder"))

        def turn(message, *, sid=session, read_only=False):
            start = time.perf_counter()
            record = {"scenario": name, "session_id": sid, "lab_batch": batch}
            try:
                result = agent.chat(message, sid, uuid.uuid4().hex,
                                    execution_mode="remote" if name == "fallback" else "local",
                                    read_only=read_only)
                record.update(compact(result), error=None)
            except RuntimeError as exc:
                if name != "tool-error":
                    raise
                record["error"] = type(exc).__name__
            record["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
            records.append(record)

        if name == "threads":
            turn("Place an order for Sony WH-CH720N Headphones")
            turn("Where is that order?")
            turn("Where is that order?", sid=session + "-new")
        elif name in {"business-denial", "replay"}:
            before = len(store.list_orders())
            turn("Place an order for Sony WH-CH720N Headphones", read_only=True)
            records[-1]["orders_added"] = len(store.list_orders()) - before
        elif name == "privacy":
            user = store.database.login("aarav@voltcart.demo", "Demo@123")[1]
            with store.use_user(user):
                turn("My email is " + user["email"] + " and my address is " + user["address"])
        else:
            turn(SEARCH)
    return records


def summarize_runs(runs) -> dict:
    """One population: completed root runs, never child spans mixed into denominators."""
    runs = list(runs)
    complete = [r for r in runs if r.end_time is not None]
    latencies = sorted((r.end_time - r.start_time).total_seconds() * 1000 for r in complete)
    n = len(complete)

    def metadata(run):
        return (run.extra or {}).get("metadata", {})

    def pct(count):
        return round(100 * count / n, 2) if n else None

    return {
        "returned_roots": len(runs), "completed_roots": n,
        "root_error_pct": pct(sum(bool(r.error) for r in complete)),
        "warning_pct": pct(sum(metadata(r).get("has_warning") is True for r in complete)),
        "business_failure_pct": pct(sum(metadata(r).get("outcome") == "failure" for r in complete)),
        "outcome_metadata_roots": sum("outcome" in metadata(r) for r in complete),
        "p50_ms": round(latencies[math.ceil(.50 * n) - 1], 1) if n else None,
        "p95_ms": round(latencies[math.ceil(.95 * n) - 1], 1) if n else None,
        "latency_method": "nearest-rank; completed root runs only",
    }


def monitor(args):
    client = live_client()
    try:
        start = datetime.now(timezone.utc) - timedelta(minutes=args.minutes)
        clauses = ['eq(name, "VoltCart chat")']
        if args.batch:
            clauses.append('and(eq(metadata_key, "lab_batch"), eq(metadata_value, ' + json.dumps(args.batch) + '))')
        runs = list(client.list_runs(project_name=config.LANGSMITH_PROJECT, is_root=True,
                                     start_time=start, filter="and(" + ", ".join(clauses) + ")",
                                     limit=args.limit))
        summary = summarize_runs(runs)
        summary.update(window_minutes=args.minutes, limit=args.limit,
                       possibly_truncated=len(runs) >= args.limit, lab_batch=args.batch)
        print(json.dumps(summary, indent=2))
        for run in runs:
            print(f"{run.id}  {run.name}  error={bool(run.error)}")
    finally:
        client.close()


def feedback(args):
    client = live_client()
    try:
        run = client.read_run(args.run_id)
        project = client.read_project(project_name=config.LANGSMITH_PROJECT)
        if run.session_id != project.id:
            raise ValueError("Run belongs to a different project. Choose a run from this classroom project.")
        result = client.create_feedback(run_id=run.id, key="student_quality", score=args.score,
                                        comment=args.comment)
        print(f"Saved feedback {result.id} on run {run.id}")
    finally:
        client.close()


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Offline by default; --live uploads synthetic classroom traces")
    run.add_argument("scenario", choices=(*SCENARIOS, "traffic"))
    run.add_argument("--live", action="store_true")
    run.add_argument("--repeat", type=positive, default=1)
    watch = sub.add_parser("monitor", help="Read root runs and compute windowed metrics from LangSmith")
    watch.add_argument("--minutes", type=positive, default=60)
    watch.add_argument("--limit", type=positive, default=1000)
    watch.add_argument("--batch")
    review = sub.add_parser("feedback", help="Add a quality score to an existing LangSmith run")
    review.add_argument("run_id", type=uuid.UUID)
    review.add_argument("--score", type=int, choices=(0, 1), required=True)
    review.add_argument("--comment", required=True)
    args = parser.parse_args()
    if args.command == "monitor":
        monitor(args)
    elif args.command == "feedback":
        feedback(args)
    else:
        if args.live:
            # Validate configuration before doing any work.
            probe = live_client()
            probe.close()
        batch = "batch-" + uuid.uuid4().hex[:12]
        records = []
        names = ("happy", "slow", "fallback", "tool-error") if args.scenario == "traffic" else (args.scenario,)
        print(f"Batch: {batch}; mode: {'LIVE upload' if args.live else 'OFFLINE (no uploads)'}", flush=True)
        for _ in range(args.repeat):
            for name in names:
                rows = run_scenario(name, live=args.live, batch=batch)
                records.extend(rows)
                for row in rows:
                    print(json.dumps(row), flush=True)
        out = config.ROOT_DIR / "labs" / "results"
        out.mkdir(exist_ok=True)
        destination = out / (batch + ".json")
        destination.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"Saved {destination}")
        if args.live:
            print("Uploads flushed. Confirm delivery in LangSmith; this message is not a delivery receipt.")
            print(f"python -m labs.langsmith_lab monitor --batch {batch}")


if __name__ == "__main__":
    main()
