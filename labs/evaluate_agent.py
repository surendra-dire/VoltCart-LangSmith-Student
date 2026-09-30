"""Deterministic regression experiments; offline by default, --live publishes to LangSmith."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from langsmith import traceable, tracing_context
from langsmith.evaluation import evaluate

import agent_service
import config
from agent_service import AgentService
from catalog import PRODUCTS_BY_ID
from labs.langsmith_lab import compact, live_client
from store import OrderStore

CASE_FILE = Path(__file__).with_name("evaluation_cases.json")


def budget_respected(outputs: dict, reference_outputs: dict) -> dict:
    products = outputs.get("products", [])
    return {"key": "budget_respected", "score": int(bool(products) and all(
        p["price"] <= reference_outputs["max_price"] for p in products))}


def nonempty_results(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "nonempty_results", "score": int(len(outputs.get("products", [])) >= reference_outputs["min_products"])}


def catalog_grounded(outputs: dict) -> dict:
    products = outputs.get("products", [])
    return {"key": "catalog_grounded", "score": int(bool(products) and all(
        p["id"] in PRODUCTS_BY_ID and p["price"] == PRODUCTS_BY_ID[p["id"]]["price"] for p in products))}


EVALUATORS = [budget_respected, nonempty_results, catalog_grounded]


def target(inputs: dict, variant: str = "baseline") -> dict:
    if variant not in {"baseline", "buggy", "fixed"}:
        raise ValueError("Unknown variant")
    with tempfile.TemporaryDirectory(prefix="voltcart-eval-") as folder, ExitStack() as stack:
        # Evaluation captures this target's compact output using the SDK wrapper below.
        # Disable the app's explicit-project tracing to keep experiment runs in one project.
        stack.enter_context(patch.object(config, "LANGSMITH_ENABLED", False))
        if variant == "buggy":
            original = agent_service.search_products

            def ignore_budget(**kwargs):
                kwargs["max_price"] = None
                return original(**kwargs)

            stack.enter_context(patch.object(agent_service, "search_products", ignore_budget))
        agent = AgentService(OrderStore(Path(folder) / "eval.db"))
        return compact(agent.chat(inputs["message"], "eval-" + uuid.uuid4().hex,
                                  execution_mode="local", read_only=True))


def local_evaluation(variant: str, cases: list[dict]) -> list[dict]:
    rows = []
    with tracing_context(enabled=False):
        for case in cases:
            output = target(case["inputs"], variant)
            scores = [budget_respected(output, case["outputs"]), nonempty_results(output, case["outputs"]),
                      catalog_grounded(output)]
            rows.append({"inputs": case["inputs"], "outputs": output,
                         "scores": {score["key"]: score["score"] for score in scores}})
    return rows


def live_evaluation(variant: str, cases: list[dict]):
    client = live_client()
    # The dataset's name records both the classroom project and the fixture revision.
    digest = hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()[:12]
    dataset_name = f"{config.LANGSMITH_PROJECT}-budget-{digest}"
    try:
        if client.has_dataset(dataset_name=dataset_name):
            dataset = client.read_dataset(dataset_name=dataset_name)
            existing = [{"inputs": e.inputs, "outputs": e.outputs} for e in client.list_examples(dataset_id=dataset.id)]
            canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
            if canonical(existing) != canonical(cases):
                raise ValueError("Cloud dataset differs from fixtures or is incomplete. Restore its examples before rerunning.")
        else:
            dataset = client.create_dataset(dataset_name=dataset_name, description="Synthetic VoltCart budget regression cases")
            client.create_examples(dataset_id=dataset.id, examples=cases)

        @traceable(name="VoltCart evaluation target")
        def predict(inputs: dict) -> dict:
            return target(inputs, variant)

        with tracing_context(enabled=True, client=client):
            results = evaluate(predict, data=dataset.name, evaluators=EVALUATORS, client=client,
                               experiment_prefix=f"voltcart-{variant}", max_concurrency=0,
                               metadata={"variant": variant, "fixture_revision": digest, "mode": "local"},
                               description="Compact deterministic recommendation evaluation; no model calls.")
            print(f"Dataset: {dataset.name}\nExperiment: {results.experiment_name}")
            # Consume results so evaluator exceptions and failed scores affect the exit code.
            failures = 0
            for row in results:
                scores = row["evaluation_results"]["results"]
                failures += int(bool(row["run"].error) or len(scores) != len(EVALUATORS)
                                or any(score.score != 1 for score in scores))
            return failures
    finally:
        client.flush()
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("baseline", "buggy", "fixed"), default="baseline")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--gate", action="store_true", help="Exit 1 if any case fails; use as a CI quality gate")
    args = parser.parse_args()
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    if args.live:
        failures = live_evaluation(args.variant, cases)
    else:
        rows = local_evaluation(args.variant, cases)
        failures = sum(any(score != 1 for score in row["scores"].values()) for row in rows)
        print(json.dumps(rows, indent=2))
    print(f"{len(cases) - failures}/{len(cases)} cases passed all evaluators ({args.variant}).")
    if args.gate and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
