"""Use real SDK trace contexts with mocked transport: no external requests."""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from langsmith import Client

import config
import observability as obs
from agent_service import AgentService
from store import OrderStore


@pytest.fixture
def traces(monkeypatch):
    monkeypatch.setattr(config, "LANGSMITH_ENABLED", True)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", "unit-test-secret")
    monkeypatch.setattr(config, "LANGSMITH_CAPTURE_CONTENT", True)
    class RecordingClient(Client):
        pass

    client = RecordingClient(api_url="http://127.0.0.1:1", api_key="test", auto_batch_tracing=False)
    client.create_run = Mock()
    client.update_run = Mock()
    monkeypatch.setattr(obs, "_client", client)
    yield client
    client.close()


def test_nested_tools_and_session_grouping(traces, tmp_path):
    agent = AgentService(OrderStore(tmp_path / "orders.json"))
    first = agent.chat("Place an order for Sony WH-CH720N Headphones", "student-a", "one")
    agent.chat("Where is that order?", "student-a", "two")
    assert first["entities"]["order"]
    runs = [call.kwargs for call in traces.create_run.call_args_list]
    roots = [r for r in runs if r["name"] == "VoltCart chat"]
    assert len(roots) == 2
    assert all(not r.get("parent_run_id") for r in roots)
    assert {r["extra"]["metadata"]["session_id"] for r in runs} == {"student-a"}
    assert any(r["name"] == "place_order" and r["run_type"] == "tool" and r["parent_run_id"] for r in runs)
    assert len(traces.update_run.call_args_list) == len(runs)


def test_disabled_tracing_ignores_environment(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setattr(config, "LANGSMITH_ENABLED", False)
    client = Mock(side_effect=AssertionError("must not initialize transport"))
    monkeypatch.setattr(obs, "_get_client", client)
    assert obs.observe()(lambda: 42)() == 42
    client.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["create_run", "update_run"])
def test_trace_failure_never_repeats_action(traces, failure_stage):
    getattr(traces, failure_stage).side_effect = RuntimeError("offline")
    action = Mock(return_value={"ok": True})

    @obs.observe()
    def commit():
        return action()

    assert commit() == {"ok": True}
    action.assert_called_once()


def test_missing_sdk_or_client_still_executes_once(monkeypatch):
    monkeypatch.setattr(config, "LANGSMITH_ENABLED", True)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", "test")
    monkeypatch.setattr(obs, "_get_client", Mock(side_effect=ImportError("missing SDK")))
    action = Mock(return_value={"ok": True})

    @obs.observe()
    def commit():
        return action()

    assert commit() == {"ok": True}
    action.assert_called_once()


def test_api_error_remains_visible_when_local_fallback_succeeds(traces, monkeypatch, tmp_path):
    agent = AgentService(OrderStore(tmp_path / "orders.json"))
    monkeypatch.setattr("agent_service.openai_is_configured", lambda: True)
    monkeypatch.setattr("agent_service.urllib.request.urlopen", Mock(side_effect=RuntimeError("unit-test-secret")))
    result = agent.chat("Recommend headphones under 10000", "fallback")
    assert result["mode"] == "local" and result["warning"]
    updates = [call.kwargs for call in traces.update_run.call_args_list]
    assert any(u.get("error") == "RuntimeError" for u in updates)
    assert any(c.kwargs["name"] == "search_products" for c in traces.create_run.call_args_list)
    assert "unit-test-secret" not in json.dumps(updates, default=str)


def test_redaction_and_llm_usage(traces, monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "model-test-secret")

    @obs.observe("llm")
    def model(payload):
        return {"choices": [{"message": {"role": "assistant", "content": "unit-test-secret"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}}

    model({"messages": [{"role": "user", "content": "model-test-secret " + config.DEMO_USER["address"]}]})
    output = traces.update_run.call_args.kwargs["outputs"]
    assert output["usage_metadata"] == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    serialized = json.dumps([c.kwargs for c in traces.create_run.call_args_list + traces.update_run.call_args_list], default=str)
    assert "model-test-secret" not in serialized
    assert "unit-test-secret" not in serialized
    assert config.DEMO_USER["address"] not in serialized


def test_metadata_only_omits_content(traces, monkeypatch):
    monkeypatch.setattr(config, "LANGSMITH_CAPTURE_CONTENT", False)

    @obs.observe()
    def chat(message, session_id):
        return {"message": message, "mode": "local"}

    chat("private chat content", "student-b")
    assert traces.create_run.call_args.kwargs["inputs"] == {}
    assert not traces.update_run.call_args.kwargs["outputs"]
    assert traces.update_run.call_args.kwargs["extra"]["metadata"]["mode"] == "local"


def test_concurrent_sessions_do_not_share_parents(traces, tmp_path):
    agent = AgentService(OrderStore(tmp_path / "orders.json"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda sid: agent.chat("Recommend headphones", sid), ["alice", "bob"]))
    runs = [c.kwargs for c in traces.create_run.call_args_list]
    roots = {r["id"]: r["extra"]["metadata"]["session_id"] for r in runs if not r.get("parent_run_id")}
    assert set(roots.values()) == {"alice", "bob"}
    for run in runs:
        assert roots[run["trace_id"]] == run["extra"]["metadata"]["session_id"]


def test_responses_usage_and_tool_format():
    output = obs._llm_outputs({"output": [{"type": "function_call", "name": "search_products", "call_id": "call-1", "arguments": "{}"}],
                               "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}})
    assert output["messages"][0]["tool_calls"][0]["function"]["name"] == "search_products"
    assert output["usage_metadata"]["total_tokens"] == 7


def test_current_cart_flow_and_local_trace_correlation(traces, tmp_path):
    store = OrderStore(tmp_path / "cart.db")
    user = store.database.login("aarav@voltcart.demo", "Demo@123")[1]
    agent = AgentService(store)
    with store.use_user(user):
        result = agent.chat("Add the Sony headphones to my cart", "cart-session", "add-1")
    assert result["actions"][0]["tool"] == "manage_cart"
    runs = [c.kwargs for c in traces.create_run.call_args_list]
    assert any(r["name"] == "manage_cart" and r["run_type"] == "tool" for r in runs)
    root_end = traces.update_run.call_args.kwargs
    assert root_end["extra"]["metadata"]["voltcart_trace_id"] == result["trace"]["id"]
    assert root_end["extra"]["metadata"]["correlation_id"] == result["trace"]["correlation_id"]


def test_read_only_replay_preserves_guardrails_and_metadata(traces, tmp_path):
    store = OrderStore(tmp_path / "replay.db")
    agent = AgentService(store)
    before = len(store.list_orders())
    result = agent.chat("Order Sony WH-CH720N Headphones", "replay-session", execution_mode="local", read_only=True)
    assert len(store.list_orders()) == before
    root = traces.create_run.call_args_list[0].kwargs
    assert root["extra"]["metadata"]["read_only"] is True
    assert root["extra"]["metadata"]["execution_mode"] == "local"
    assert any(g["decision"] == "deny_read_only_replay" for g in result["trace"]["guardrails"])


def test_signed_in_customer_details_are_redacted(traces, tmp_path):
    store = OrderStore(tmp_path / "privacy.db")
    user = store.database.login("aarav@voltcart.demo", "Demo@123")[1]
    agent = AgentService(store)
    with store.use_user(user):
        agent.chat("My address is " + user["address"] + " and my email is " + user["email"], "privacy")
    captured = json.dumps([c.kwargs for c in traces.create_run.call_args_list + traces.update_run.call_args_list], default=str)
    assert user["address"] not in captured
    assert user["email"] not in captured
