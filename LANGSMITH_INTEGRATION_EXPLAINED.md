# How LangSmith was integrated into VoltCart

## A simple, step-by-step code walkthrough

**Read this first if you want to understand the integration code.** Use the [hands-on workbook](LANGSMITH_STUDENT_WORKBOOK.md) afterward to practise debugging and monitoring.

VoltCart already had a shopping agent, Python tools, and a local database. LangSmith was added to record what those functions do: their inputs, outputs, duration, and errors. Shopping decisions and order rules still run in VoltCart.

This guide explains the code currently in this folder. The short excerpts show the important lines; they are **not replacements for the complete source files**. The commands in Step 10 run the existing implementation.

## The overall flow

```text
Student sends a chat message
          |
          v
app.py receives the request
          |
          v
AgentService.chat()              -> LangSmith: VoltCart chat
          |
          +-- local agent        -> LangSmith: Local demo agent
          |      +-- search     -> LangSmith: search_products
          |
          +-- remote agent       -> LangSmith: Remote agent
                 +-- model call -> LangSmith: Model request
                 +-- tool call  -> LangSmith: the tool's name

The agent returns its normal response to the student.
LangSmith receives a record of the instrumented execution.
```

A **run**, also called a span, records one operation. A **trace** groups the top-level run and its child runs for a request.

## Step 1 — Install the LangSmith SDK

**File: [requirements.txt](requirements.txt)**

```text
langsmith==0.12.6
```

The SDK is the Python library that sends trace records to LangSmith. The version is pinned so students use the same SDK version.

From this project folder, install the dependencies using the supplied setup:

```powershell
.\setup.bat
```

VoltCart does not need to be rewritten with LangChain. Its existing Python functions and HTTP model calls can be traced directly.

## Step 2 — Add the connection settings

**File: [config.py](config.py)**

```python
LANGSMITH_ENABLED = False
LANGSMITH_API_KEY = "PASTE_YOUR_LANGSMITH_API_KEY_HERE"
LANGSMITH_PROJECT = "voltcart-student-demo"
LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
LANGSMITH_WORKSPACE_ID = ""
LANGSMITH_CAPTURE_CONTENT = True
```

| Setting | What it does |
| --- | --- |
| `LANGSMITH_ENABLED` | Turns the application's tracing on or off. |
| `LANGSMITH_API_KEY` | Authenticates to LangSmith. This is separate from the model API key. |
| `LANGSMITH_PROJECT` | Chooses where the traces appear. |
| `LANGSMITH_ENDPOINT` | Chooses the LangSmith API region; EU uses `https://eu.api.smith.langchain.com`. |
| `LANGSMITH_WORKSPACE_ID` | Selects a workspace when required by the key. |
| `LANGSMITH_CAPTURE_CONTENT` | Controls whether application inputs and outputs are included. |

To enable tracing, replace the key placeholder and set `LANGSMITH_ENABLED = True`. Save and restart the app. Keep the configured file private.

This project reads these values directly from `config.py`; environment variables are not required.

## Step 3 — Create one reusable LangSmith client

**File: [observability.py](observability.py), function: `_get_client()`**

The client construction uses:

```python
from langsmith import Client

_client = Client(
    api_url=config.LANGSMITH_ENDPOINT,
    api_key=config.LANGSMITH_API_KEY,
    workspace_id=config.LANGSMITH_WORKSPACE_ID or None,
    timeout_ms=2000,
    auto_batch_tracing=True,
    tracing_error_callback=lambda exc: _warn(),
)
```

`Client` handles communication with LangSmith. `auto_batch_tracing=True` allows background batching of trace uploads. The timeout applies to LangSmith communication, not to the shopping model's request timeout. `_warn()` reports a tracing problem locally.

The full function stores the client in `_client` and uses a thread lock when creating it. The server can handle multiple requests, so it reuses one client instead of constructing a new one for every tool call.

## Step 4 — Build a reusable tracing decorator

**File: [observability.py](observability.py), function: `observe()`**

A decorator wraps a function with extra behavior. In this integration, the extra behavior is recording execution:

```text
Start a trace span
    -> call the original function once
    -> record its result or error
    -> close the trace span
```

The decorator starts with this structure:

```python
def observe(run_type="chain", name=None):
    def decorate(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            if not _configured():
                return function(*args, **kwargs)
            # The remaining implementation records the execution.

        return wrapped
    return decorate
```

What each part means:

- `run_type` classifies the operation: `chain`, `tool`, or `llm`.
- `name` is the readable label shown in LangSmith.
- `function` is the original business function being wrapped.
- `*args` and `**kwargs` receive its positional and named arguments.
- `functools.wraps` preserves the original function's identity for Python tools.
- `_configured()` checks that tracing is enabled and a non-placeholder key exists. Otherwise, the function runs normally without this tracing wrapper uploading anything.

This shared decorator keeps the tracing logic in one file. Each shopping function only needs a small annotation.

### How the wrapper collects inputs

```python
bound = signature.bind(*args, **kwargs)
values = {
    k: v for k, v in bound.arguments.items()
    if k not in {"self", "state"}
}
```

`signature.bind` maps arguments to names such as `message` and `session_id`. The wrapper excludes the Python object `self` and the internal `state` object. Selected inputs are cleaned before upload.

### How it starts a span

The important lines inside the wrapper are:

```python
stack.enter_context(tracing_context(
    enabled=True,
    client=client,
    metadata=_clean(metadata),
))

run = stack.enter_context(trace(
    trace_name,
    run_type=run_type,
    client=client,
    project_name=config.LANGSMITH_PROJECT,
    inputs=_clean(values, private_values)
        if config.LANGSMITH_CAPTURE_CONTENT else {},
    metadata=_clean(metadata),
))
```

`tracing_context` establishes tracing settings for the current execution. `trace` opens the actual span. `ExitStack`, stored in `stack`, closes both contexts when the function finishes. The SDK records start/end times used to calculate duration.

When another decorated function runs inside the current span, the tracing context lets LangSmith connect it as a child. The code does not need to manually connect parent and child IDs for each function call.

## Step 5 — Add decorators to the important agent functions

**File: [agent_service.py](agent_service.py)**

First, import the wrapper:

```python
from observability import observe
```

Then annotate the functions. These are the actual annotations in the source:

| Function | Annotation | What appears in LangSmith |
| --- | --- | --- |
| `chat` | `@observe(name="VoltCart chat")` | Top-level chat turn |
| `_chat_local` | `@observe(name="Local demo agent")` | Local-agent execution |
| `_chat_openai` | `@observe(name="Remote agent")` | Remote-agent execution |
| `_post_json` | `@observe("llm", name="Model request")` | Model HTTP call |
| `_execute_tool` | `@observe("tool")` | The requested tool's execution |
| `_local_search` | `@observe("tool", name="search_products")` | Local catalog search |
| `_ensure_remote_intent_completion` | `@observe(name="Complete requested action")` | Additional remote intent-completion checks |

For example, the chat method begins:

```python
@observe(name="VoltCart chat")
def chat(
    self,
    message: str,
    session_id: str,
    message_id: str = "",
    execution_mode: str = "current",
    read_only: bool = False,
) -> dict[str, Any]:
    # Existing chat implementation continues here.
```

The application still calls `agent.chat(...)` normally. The decorator adds the recording around it.

For the generic tool dispatcher, the wrapper chooses the tool name dynamically:

```python
if run_type == "tool" and "name" in values:
    trace_name = values["name"]
```

So a call to `_execute_tool("place_order", arguments)` appears as **place_order**, rather than every tool appearing as `_execute_tool`.

## Step 6 — Record results, errors, and useful labels

**File: [observability.py](observability.py), inside `wrapped()`**

The business function executes at this line:

```python
result = function(*args, **kwargs)
```

On success, the wrapper cleans the output and ends the span:

```python
outputs = _clean(output, private_values) \
    if config.LANGSMITH_CAPTURE_CONTENT else {}
run.end(outputs=outputs)
```

If the business function raises an exception, the wrapper records its class and lets the application handle the exception normally:

```python
run.end(error=type(exc).__name__)
```

The full handler then uses `raise` to propagate that exception. It does not upload the exception message or Python traceback, which could contain private values.

Tracing setup, upload, or cleanup failures are handled separately with `_warn()`. They do not cause the business function to be retried. This matters for shopping: a failed telemetry upload must not place an order twice.

### Add session and outcome metadata

The wrapper records labels such as:

```python
metadata["session_id"] = values["session_id"]
metadata["message_id"] = values.get("message_id", "")
metadata["execution_mode"] = values.get("execution_mode", "current")
metadata["read_only"] = values.get("read_only", False)
```

`session_id` groups turns into a conversation in LangSmith. `message_id` identifies the application turn. `read_only` helps identify replay behavior. The wrapper also preserves caller metadata, such as the classroom lab's batch label.

After a response is available, it adds `mode`, `has_warning`, and local trace details when present:

```python
details.update(
    voltcart_trace_id=local_trace.get("id"),
    correlation_id=local_trace.get("correlation_id"),
    outcome=local_trace.get("outcome"),
)
run.add_metadata(details)
```

This links a LangSmith trace to VoltCart's existing local trace. A VoltCart `TRC-...` ID is different from a LangSmith run UUID.

**Important example:** if a model request fails but the local fallback succeeds, the root can show a successful response while the model child shows an error. `has_warning=true` explains the recovery. Similarly, a tool returning `ok=false` is a structured denial, not necessarily a thrown exception.

## Step 7 — Format model calls and token usage

**Files: [agent_service.py](agent_service.py) and [observability.py](observability.py)**

VoltCart already sends model requests through `_post_json()`, using Python's HTTP library. Decorating that function captures model execution without changing its transport:

```python
@observe("llm", name="Model request")
def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    # Existing HTTP request implementation continues here.
```

The wrapper uses `_llm_inputs()` and `_llm_outputs()` to prepare model messages for tracing. It supports the existing Chat Completions and Responses API shapes. These conversions affect telemetry, not the original response returned to the agent.

`_usage()` normalizes token fields:

```python
return {
    "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
    "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
    "total_tokens": usage.get("total_tokens", 0),
}
```

For example, provider usage with 100 prompt tokens and 20 completion tokens is recorded as 100 input tokens and 20 output tokens. The normalized data is attached as `usage_metadata`.

The wrapper also sets `ls_provider="openai"` and `ls_model_name=config.OPENAI_MODEL`. LangSmith cost estimates depend on recognized model pricing; a custom Azure deployment name may need custom pricing. Local-agent runs have no real model usage.

## Step 8 — Clean the data before sending it

**File: [observability.py](observability.py), function: `_clean()`**

Cleaning is applied to trace inputs, outputs, and metadata. The cleaner walks through dictionaries, lists, and strings. It redacts known credential/customer values and sensitive fields such as `password`, `authorization`, and `session_token`. Unsupported objects are omitted.

For a dictionary such as:

```python
{"email": "learner@example.test", "quantity": 1}
```

the email field is replaced with a redaction marker while the quantity remains usable for debugging.

The wrapper also obtains known details of the current customer so those values can be removed from captured prompt text.

Set `LANGSMITH_CAPTURE_CONTENT = False` to omit application input/output content while retaining timing and metadata. Model usage can still be recorded. This setting affects future application traces; it does not delete earlier uploads, and it does not control the separate evaluation script's explicit synthetic dataset uploads.

The cleaner is not a complete detector of private information in arbitrary prose. Use classroom data in the demo.

## Step 9 — Report tracing status and flush on shutdown

**File: [app.py](app.py)**

The app imports the helper functions:

```python
from observability import flush, status as tracing_status
```

At startup it displays:

```python
print(f"LangSmith: {tracing_status()}")
```

When the server exits, its `finally` block calls:

```python
server.server_close()
flush()
```

`flush()` asks the SDK to finish pending uploads, with a short timeout. This is useful because tracing uses background batching. A startup “enabled” message confirms configuration; a visible trace in LangSmith confirms delivery.

## Step 10 — Run and verify the integration

Run these commands from the project root after setup:

```powershell
# Run real VoltCart code with temporary data, without uploading.
.\.venv\Scripts\python.exe -m labs.langsmith_lab run happy

# After configuring LangSmith, upload the same exercise.
.\.venv\Scripts\python.exe -m labs.langsmith_lab run happy --live
```

Open your LangSmith project and match the printed session/batch ID. Expected tree:

```text
VoltCart chat
  Local demo agent
    search_products
```

Select each span and inspect its inputs, outputs, and duration. No model key is required for this local exercise.

Then run the existing integration checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_observability.py -q
```

These tests use real SDK trace contexts with mocked transport. They check nested spans, session grouping, usage formatting, redaction, fallback, and that tracing failure does not execute an action twice. They do not upload traces or make paid model calls.

To observe browser requests, start the app and send a chat message:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:8000>. Chat turns are instrumented; direct non-chat API operations are not automatically LangSmith spans.

## Where to look in the code

| File | Role in the integration |
| --- | --- |
| `requirements.txt` | Installs the SDK. |
| `config.py` | Stores connection and capture settings. |
| `observability.py` | Creates the client, wraps functions, cleans payloads, records results/errors, and flushes uploads. |
| `agent_service.py` | Marks the chat, agent, model, and tool functions to trace. |
| `app.py` | Prints tracing status and flushes on shutdown. |
| `tests/test_observability.py` | Verifies the integration without network uploads. |
| `labs/` | Adds classroom fault demonstrations, monitoring, feedback, and evaluation on top of the integration. |

**A useful distinction:** instrumentation produces execution evidence. Monitoring summarizes that evidence, and evaluators judge whether outputs satisfy requirements. Adding traces alone does not automatically evaluate answer quality.
