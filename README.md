# VoltCart with LangSmith — student edition

A local electronics shopping-agent demo with optional LangSmith tracing. All
connection settings are in **config.py**. No environment variables, JSON
credential file, LangChain migration, database setup, or frontend build is needed.

## Read the student guides in your browser

Double-click **[START_HERE.html](START_HERE.html)** for all student guides, including
the **[LangSmith hands-on workbook](LANGSMITH_STUDENT_WORKBOOK.html)**. The HTML
pages work offline, include a table of contents and copy buttons for commands,
and support **Print / Save PDF**. No Markdown viewer is required.

For a simple explanation of the integration code, read
**[How LangSmith was integrated into VoltCart](LANGSMITH_INTEGRATION_EXPLAINED.html)**.

## Start on Windows

1. Install **Python 3.10 or newer** with Python available on PATH.
2. Extract the ZIP completely. Do not run files from inside the ZIP viewer.
3. Open `config.py` in a text editor and change the settings below. Keep strings
   inside quotes; Python booleans are `True` and `False`.
4. Double-click `start_demo.bat`. First use creates a `.venv` and installs the
   dependencies automatically, requiring internet access. You can also run
   `setup.bat` separately before class.
5. Open **http://127.0.0.1:8000** and sign in with `aarav@voltcart.demo` /
   `Demo@123`, or register a learner account. Leave the console running.
   Press Ctrl+C to stop.

Save `config.py` and restart the server after changing any setting.

## Settings students change

| Variable in config.py | Value to use |
| --- | --- |
| `OPENAI_API_KEY` | Your authorized model API key |
| `OPENAI_BASE_URL` | Your Azure resource URL ending in `/openai/v1`; do not append `/chat/completions` |
| `OPENAI_MODEL` | Your deployment name; the default matches the current source, `gpt-5.4-nano` |
| `OPENAI_API_MODE` | Usually `"chat_completions"`; optional `"responses"` requires a compatible deployment |
| `OPENAI_AUTH_HEADER` | `"api-key"` for Azure; `"Authorization"` for a Bearer key |
| `LANGSMITH_ENABLED` | Change to `True` to enable tracing |
| `LANGSMITH_API_KEY` | Your separate LangSmith API key from account/workspace settings |
| `LANGSMITH_PROJECT` | A project name you choose, such as `voltcart-priya` |
| `LANGSMITH_ENDPOINT` | Keep the US default, or use `https://eu.api.smith.langchain.com` for an EU workspace |
| `LANGSMITH_WORKSPACE_ID` | Usually empty; supply your workspace ID when required by your key |

The model key and LangSmith key belong to different services and are not interchangeable.
Use a deployment compatible with the selected API mode and request parameters.
Advanced model request parameters are also in `config.py`.

The downloaded ZIP contains **placeholder keys only**. Keep your configured copy
private. To share with another student, share the original ZIP instead of your
edited folder. A separate project name organizes traces but does not grant or
restrict workspace access.

## Verify LangSmith

1. Set `LANGSMITH_ENABLED = True` and enter your LangSmith key. Restart the app.
2. Send `Recommend headphones under 10000` in the web chat.
3. Open LangSmith in the region matching your endpoint and open the project named
   by `LANGSMITH_PROJECT`. Allow a few seconds for background uploads.
4. Inspect `VoltCart chat`, then its `Remote agent` or `Local demo agent` child.
   Remote runs include `Model request` calls and named tools. Local search is
   traced as `search_products`. The existing UI Action log remains available.
5. Send another message in the same browser conversation. Its `session_id`
   groups the turns in LangSmith's Threads view.

The app's existing SQLite traces, replay, export and metrics features are also
included. LangSmith root metadata includes `voltcart_trace_id` and `correlation_id`
so you can match the two views. Replays retain the source application's read-only
guardrails. Direct non-chat API operations are not automatically LangSmith spans.

You can test LangSmith with **only a LangSmith key**: leave the model settings at
their placeholders and the app will trace the deterministic local agent. These
traces have no model token usage. A startup message saying tracing is enabled
describes configuration; a visible trace confirms a successful connection.

If traces do not appear, check the console, dependencies, key, endpoint region,
workspace ID, project name, and network access. Model failure can fall back to
local mode; inspect the remote error span and the response warning. Tracing
failure does not retry a shopping action or block use of the local app.

Token counts are recorded when the model returns usage. LangSmith cost estimates
depend on recognized model names/pricing; custom Azure deployment names or rates
may require custom pricing in LangSmith.
The built-in VoltCart metrics retain the source's illustrative fixed token rates;
they are not an Azure billing statement.

## What is uploaded

With tracing enabled, prompts, responses, tool arguments/results, session IDs,
timing, and outcome metadata are sent to your LangSmith workspace. Known API keys
and known signed-in customer names, email addresses, phone numbers and addresses
are redacted. Password fields, session-token fields and attachments are omitted.
Arbitrary text
typed into chat is not a general-purpose PII filter; use classroom data.

Set `LANGSMITH_CAPTURE_CONTENT = False` to omit input/output content while keeping
timing, session IDs, outcome metadata and any model token counts. Set
`LANGSMITH_ENABLED = False` to disable this application's tracing entirely,
regardless of ambient LangSmith environment settings.

## Classroom exercises

For step-by-step teaching, use the **[LangSmith student workbook](LANGSMITH_STUDENT_WORKBOOK.md)**.
It includes 12 practical labs, optional model/online-evaluation labs, expected
observations, troubleshooting, and an assessment rubric. Executable scripts in
`labs/` demonstrate slow tools, exceptions, fallback, business denials, monitoring,
feedback, and baseline/buggy/fixed evaluation experiments. Core labs need no model
key; add `--live` and a LangSmith key to inspect real uploads in your workspace.

```powershell
.\.venv\Scripts\python.exe -m labs.langsmith_lab run happy
.\.venv\Scripts\python.exe -m labs.langsmith_lab run happy --live
.\.venv\Scripts\python.exe -m labs.evaluate_agent --variant fixed --gate
```

- `Place an order for Sony WH-CH720N Headphones`, then `Where is that order?`
- `Build a gaming setup under 90000 with a laptop, mouse and headphones`
- Send the exact `Approve APR-...` command from the plan in a later message.
- Compare `Can I cancel it?` with `Cancel that order` in the tool results.
- `Can I return order ORD-DEMO-1001?`
- `Summarize verified reviews for Sony WH-CH720N Headphones`
- `Create a support ticket: my delivered earbuds are damaged`
- `Remember my budget is 80000, I prefer Sony, and exclude Apple`
- `Add the Sony headphones to my cart`, then `Checkout my cart`
- Compare remote model behavior with local fallback or the built-in replay tools.

Purchases above INR 50,000 and all bundles require a later approval. Orders,
stock, approvals and return policies are enforced by Python. This is a local
teaching demo with simulated payments, learner accounts, and always-available
inventory so scenarios can be repeated. See `APP_GUIDE.md` for the complete
current feature guide.

Each extracted copy starts with fresh seeded learner accounts, reviews and demo
orders; the SQLite file `data/voltcart.db` is created automatically on first run.
No database server is required. **Reset demo** restores the teaching order data. Browser and
Postman sessions are separate unless they use the same `session_id`.

## macOS / Linux or manual setup

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Windows manual equivalent after running `setup.bat`:

```powershell
.\.venv\Scripts\python.exe app.py
```

## Tests and files

Windows: `.\.venv\Scripts\python.exe -m pytest -q`

macOS/Linux with the environment activated: `python -m pytest -q`

Tests use simulated model responses and mocked trace transport. They make no
paid model calls and do not upload traces, including when your config has keys.
HTTP tests use a temporary order store rather than your demo orders.

- `config.py`: all student settings
- `app.py`: local HTTP server
- `agent_service.py`: model/tool loops and local fallback
- `observability.py`: optional tracing and redaction
- `database.py`, `store.py`, `catalog.py`: SQLite persistence, shopping data and rules
- `static/`: browser UI
- `API_GUIDE.md`, `postman/`: API examples and Postman collection
- `VoltCart_AI_Agent_Test_Cases_100.csv`: classroom test-case reference

Integration reference: https://docs.langchain.com/langsmith/annotate-code
