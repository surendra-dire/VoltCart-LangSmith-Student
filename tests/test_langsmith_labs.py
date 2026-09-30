"""Classroom exercises must be repeatable and safe without cloud/model credentials."""
import json
import socket
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langsmith import Client
from langsmith import schemas, tracing_context
from langsmith.evaluation import evaluate

import config
from labs import langsmith_lab as lab
from labs.evaluate_agent import CASE_FILE, EVALUATORS, budget_respected, catalog_grounded, local_evaluation, target


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("Labs tests must not use network")))


@pytest.mark.parametrize("name", lab.SCENARIOS)
def test_scenario_contract(name):
    rows = lab.run_scenario(name)
    first = rows[0]
    if name == "tool-error":
        assert first["error"] == "RuntimeError"
    else:
        assert first["error"] is None
        assert first["mode"] == "local"
    if name == "slow":
        assert first["elapsed_ms"] >= 1100
    elif name == "fallback":
        assert first["has_warning"] is True
    elif name == "business-denial":
        assert first["tool_denials"] == 1 and first["outcome"] == "failure"
        assert first["orders_added"] == 0
    elif name == "replay":
        assert first["orders_added"] == 0
        assert any(g["decision"] == "deny_read_only_replay" for g in first["guardrails"])
    elif name == "threads":
        assert len(rows) == 3
        assert rows[0]["session_id"] == rows[1]["session_id"] != rows[2]["session_id"]
        assert rows[0]["order_id"] == rows[1]["order_id"]


@pytest.mark.parametrize("variant,expected", [("baseline", 4), ("buggy", 1), ("fixed", 4)])
def test_regression_and_recovery(variant, expected):
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    rows = local_evaluation(variant, cases)
    assert sum(all(row["scores"].values()) for row in rows) == expected


def test_evaluators_reject_empty_and_invented_products():
    assert budget_respected({"products": []}, {"max_price": 2000})["score"] == 0
    assert catalog_grounded({"products": [{"id": "MADE-UP", "price": 1}]})["score"] == 0
    assert catalog_grounded({"products": [{"id": "AUD-301", "price": 1}]})["score"] == 0


def test_official_sdk_evaluation_contract_without_uploads():
    case = json.loads(CASE_FILE.read_text(encoding="utf-8"))[1]
    example = schemas.Example(id=uuid.uuid4(), dataset_id=uuid.uuid4(),
                              created_at=datetime.now(timezone.utc), **case)
    client = Client(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    try:
        with tracing_context(enabled=False):
            results = evaluate(lambda inputs: target(inputs, "buggy"), data=[example],
                               evaluators=EVALUATORS, client=client, upload_results=False,
                               max_concurrency=0)
            rows = list(results)
        scores = {s.key: s.score for s in rows[0]["evaluation_results"]["results"]}
        assert scores == {"budget_respected": 0, "nonempty_results": 1, "catalog_grounded": 1}
    finally:
        client.close()


def test_monitor_counts_completed_roots_and_nearest_rank():
    start = datetime.now(timezone.utc)
    runs = [SimpleNamespace(start_time=start, end_time=start + timedelta(milliseconds=ms),
                            error="RuntimeError" if i == 3 else None,
                            extra={"metadata": {"has_warning": i == 2, "outcome": "failure" if i == 1 else "success"}})
            for i, ms in enumerate([10, 20, 30, 1200])]
    runs.append(SimpleNamespace(start_time=start, end_time=None))
    result = lab.summarize_runs(runs)
    assert result["completed_roots"] == 4 and result["returned_roots"] == 5
    assert result["root_error_pct"] == result["warning_pct"] == result["business_failure_pct"] == 25
    assert result["p50_ms"] == 20 and result["p95_ms"] == 1200
    assert lab.summarize_runs([])["p95_ms"] is None


@pytest.mark.parametrize("name", ["happy", "fallback", "business-denial", "tool-error", "privacy"])
def test_live_trace_structure_with_mocked_transport(monkeypatch, name):
    class RecordingClient(Client):
        pass

    client = RecordingClient(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    client.create_run = Mock()
    client.update_run = Mock()
    monkeypatch.setattr(lab, "live_client", lambda: client)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", "lab-test-secret")
    lab.run_scenario(name, live=True, batch="verification-batch")
    runs = [c.kwargs for c in client.create_run.call_args_list]
    updates = [c.kwargs for c in client.update_run.call_args_list]
    roots = [r for r in runs if not r.get("parent_run_id")]
    assert len(roots) == 1 and roots[0]["name"] == "VoltCart chat"
    assert roots[0]["extra"]["metadata"]["lab_batch"] == "verification-batch"
    by_id = {u["run_id"]: u for u in updates}
    root = by_id[roots[0]["id"]]
    if name == "tool-error":
        assert root["error"] == "RuntimeError"
    elif name == "fallback":
        assert not root.get("error")
        model = next(r for r in runs if r["name"] == "Model request")
        assert by_id[model["id"]]["error"] == "TimeoutError"
        assert root["extra"]["metadata"]["has_warning"] is True
    elif name == "business-denial":
        denied = next(r for r in runs if r["name"] == "place_order")
        assert by_id[denied["id"]]["outputs"]["ok"] is False
        assert not by_id[denied["id"]].get("error")
    elif name == "privacy":
        captured = json.dumps(runs + updates, default=str)
        assert "aarav@voltcart.demo" not in captured
        assert "lab-test-secret" not in captured
