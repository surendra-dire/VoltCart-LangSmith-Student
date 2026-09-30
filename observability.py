"""Optional LangSmith tracing configured exclusively through config.py.

Telemetry never retries an application action and never changes its result.
"""
from __future__ import annotations

import functools
import inspect
import re
import sys
import threading
from contextlib import ExitStack

import config

_client = None
_client_lock = threading.Lock()
_warned = False


def _warn() -> None:
    global _warned
    if not _warned:
        _warned = True
        print("LangSmith tracing unavailable. Check config.py, your connection, and dependencies; the demo will continue.", file=sys.stderr)


def _configured() -> bool:
    key = config.LANGSMITH_API_KEY.strip()
    return config.LANGSMITH_ENABLED and bool(key) and not key.startswith("PASTE_")


def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from langsmith import Client
                _client = Client(
                    api_url=config.LANGSMITH_ENDPOINT,
                    api_key=config.LANGSMITH_API_KEY,
                    workspace_id=config.LANGSMITH_WORKSPACE_ID or None,
                    timeout_ms=2000,
                    auto_batch_tracing=True,
                    tracing_error_callback=lambda exc: _warn(),
                )
    return _client


def _clean(value, private_values=()):
    """Exclude known credentials/customer fields, including inside prompt strings."""
    if isinstance(value, dict):
        return {
            str(k): "<redacted>" if str(k).lower() in {
                "api_key", "api-key", "authorization", "email", "address", "delivery_address",
                "shipping_address", "phone", "password", "password_hash", "password_salt",
                "session_token", "attachments",
            } else _clean(v, private_values)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_clean(v, private_values) for v in value]
    if isinstance(value, str):
        for secret in (
            config.OPENAI_API_KEY, config.LANGSMITH_API_KEY,
            config.DEMO_USER["email"], config.DEMO_USER["address"], config.DEMO_USER["name"],
            *private_values,
        ):
            if secret:
                value = value.replace(secret, "<redacted>")
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<redacted-email>", value)
        return re.sub(r"\b\d{10,15}\b", "<redacted-phone>", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "<omitted>"


def _usage(output):
    usage = output.get("usage", {})
    if not usage:
        return {}
    return {
        "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
        "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _llm_inputs(payload):
    if "messages" in payload:
        return payload
    messages = []
    if payload.get("instructions"):
        messages.append({"role": "system", "content": payload["instructions"]})
    for item in payload.get("input", []):
        if item.get("type") == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item.get("call_id"), "content": item.get("output")})
        else:
            messages.append(item)
    return {**payload, "messages": messages}


def _llm_outputs(output):
    if "choices" in output:
        return {**output, "usage_metadata": _usage(output)}
    messages = []
    for item in output.get("output", []):
        if item.get("type") == "message":
            content = "\n".join(part.get("text", part.get("refusal", "")) for part in item.get("content", []))
            messages.append({"role": "assistant", "content": content})
        elif item.get("type") == "function_call":
            messages.append({"role": "assistant", "content": "", "tool_calls": [{
                "id": item.get("call_id"), "type": "function",
                "function": {"name": item.get("name"), "arguments": item.get("arguments")},
            }]})
    return {"messages": messages, "usage_metadata": _usage(output)}


def observe(run_type="chain", name=None):
    def decorate(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            if not _configured():
                return function(*args, **kwargs)
            stack = ExitStack()
            run = None
            try:
                from langsmith import get_tracing_context, trace, tracing_context
                bound = signature.bind(*args, **kwargs)
                owner = bound.arguments.get("self")
                user = owner.store.current_user() if owner is not None and hasattr(owner, "store") else {}
                private_values = tuple(user.get(k, "") for k in ("name", "email", "address", "phone"))
                values = {k: v for k, v in bound.arguments.items() if k not in {"self", "state"}}
                # Preserve caller context, e.g. a classroom batch or release label.
                metadata = dict(get_tracing_context().get("metadata") or {})
                if "session_id" in values:
                    metadata["session_id"] = values["session_id"]
                    metadata["message_id"] = values.get("message_id", "")
                    metadata["execution_mode"] = values.get("execution_mode", "current")
                    metadata["read_only"] = values.get("read_only", False)
                    metadata["user_id"] = user.get("id", "")
                trace_name = name or function.__name__
                if run_type == "tool" and "name" in values:
                    trace_name = values["name"]
                if run_type == "llm":
                    values = _llm_inputs(values["payload"])
                    metadata.update(ls_provider="openai", ls_model_name=config.OPENAI_MODEL)
                client = _get_client()
                stack.enter_context(tracing_context(enabled=True, client=client, metadata=_clean(metadata)))
                run = stack.enter_context(trace(
                    trace_name, run_type=run_type, client=client,
                    project_name=config.LANGSMITH_PROJECT,
                    inputs=_clean(values, private_values) if config.LANGSMITH_CAPTURE_CONTENT else {},
                    metadata=_clean(metadata),
                ))
            except Exception:
                _warn()
                try:
                    stack.close()
                except Exception:
                    pass
                run = None

            # Call the business function exactly once, even if telemetry fails.
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                if run is not None:
                    try:
                        # Do not upload exception messages/tracebacks containing local data.
                        run.end(error=type(exc).__name__)
                    except Exception:
                        _warn()
                raise
            else:
                if run is not None:
                    try:
                        output = _llm_outputs(result) if run_type == "llm" else result
                        if isinstance(result, dict):
                            details = {k: result[k] for k in ("mode", "ok") if k in result}
                            details["has_warning"] = bool(result.get("warning"))
                            local_trace = result.get("trace", {})
                            if local_trace:
                                details.update(
                                    voltcart_trace_id=local_trace.get("id"),
                                    correlation_id=local_trace.get("correlation_id"),
                                    outcome=local_trace.get("outcome"),
                                )
                            run.add_metadata(details)
                        outputs = _clean(output, private_values) if config.LANGSMITH_CAPTURE_CONTENT else {}
                        if run_type == "llm" and _usage(result):
                            outputs["usage_metadata"] = _usage(result)
                        run.end(outputs=outputs)
                    except Exception:
                        _warn()
                return result
            finally:
                try:
                    stack.close()
                except Exception:
                    _warn()

        return wrapped
    return decorate


def status() -> str:
    if not config.LANGSMITH_ENABLED:
        return "off (enable LANGSMITH_ENABLED in config.py)"
    if not _configured():
        return "off (add LANGSMITH_API_KEY in config.py)"
    try:
        _get_client()
    except Exception:
        return "unavailable (run setup.bat or install requirements.txt)"
    return f"enabled for project {config.LANGSMITH_PROJECT!r}; connection is checked when traces are sent"


def flush() -> None:
    if _client is not None:
        try:
            _client.flush(timeout=3)
        except Exception:
            _warn()
