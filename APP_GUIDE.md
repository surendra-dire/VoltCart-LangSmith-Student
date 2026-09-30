# VoltCart — AI shopping-agent classroom demo

VoltCart is a deliberately small electronics store that demonstrates an **agent
using tools to take real actions**. A student can ask the chat assistant to find
products, build a multi-product setup within a budget, request human approval
before a bundle or high-value purchase, place and track orders, cancel eligible
orders, and create return or same-product exchange requests. The backend—not
the model—owns prices, inventory, approval rules, return rules, and persistence.

The project has 26 fixed products, two seeded learner accounts, three seeded
orders, 78 verified demo reviews, FAQs and support tickets. SQLite is created
and seeded automatically; there is no database server, admin UI, build step or
separate database installation.

Inventory is intentionally **always available** in this classroom edition. An
order never exhausts stock, so every student can replay the same scenarios. The
UI and agent still execute the availability-validation step so it remains
observable and testable.

## Start in under a minute

You need Python 3.10 or newer.

### Windows

Double-click `start_demo.bat`, or run:

```powershell
cd ecommerce_agent_demo
python app.py
```

### macOS / Linux

```bash
cd ecommerce_agent_demo
python3 app.py
```

Open <http://127.0.0.1:8000>. Sign in with `aarav@voltcart.demo` / `Demo@123`
(or register a new user), then try:

- `Place an order for Sony WH-CH720N Headphones`
- `Where is that order?`
- `Can I cancel it?` (information only)
- `Cancel that order` (takes the action)
- `Recommend headphones under ₹10,000`
- `Is the MacBook Air M2 in stock?`
- `Show my recent orders`
- `Build a gaming setup under 90000 with a laptop, mouse and headphones`
- `Approve APR-...` (use the exact token shown by the plan)
- `Order MacBook Air M2` (requires approval because it is over ₹50,000)
- `Can I return order ORD-DEMO-1001?` (eligibility only)
- `Return order ORD-DEMO-1001 because the earbuds are defective`
- `Exchange my delivered boAt Airdopes 141 for a replacement`
- `Track return request RET-... for order ORD-DEMO-1001`
- `Summarize verified reviews for Sony WH-CH720N Headphones`
- `What is the cancellation policy?`
- `Create a support ticket: my delivered earbuds are damaged`
- `Show my support tickets`
- `Escalate ticket SUP-... to a human agent`
- `Compare Sony WH-CH720N, JBL Flip 6 and OnePlus Buds 3 for calls and travel`
- `Add the Sony headphones, remove the mouse and change the laptop quantity to two`
- `Remember my budget is 80000, I prefer Sony, and exclude Apple`
- `Change the delivery slot for order ORD-DEMO-1003 to Saturday`
- `Do any of my orders need proactive assistance?`
- `For order ORD-DEMO-1001, should I get a refund or replacement?`

## Test the agent API with Postman

Import `postman/VoltCart-Agent-API.postman_collection.json` into Postman and run
the requests from top to bottom. Besides the basic order flow, the collection
builds a deterministic budget mission, captures its approval token, approves it
in a later turn, demonstrates the high-value checkpoint, creates and tracks
refund-return and replacement-exchange requests, and resets the demo.

The local base URL is `http://127.0.0.1:8000`. Visit
<http://127.0.0.1:8000/api> for API discovery, or read `API_GUIDE.md` for request
and response examples. API writes intentionally use `POST /api/chat`, allowing
students to inspect the agent's tool calls instead of bypassing the agent.

## Student configuration

All connection settings are in `config.py`. See `README.md` for setup, model
and LangSmith configuration, sign-in, and tracing verification. No separate
credential JSON file is used in this edition.

## What makes this agentic?

A normal chatbot only generates text. VoltCart gives the model a small set of
server-side tools:

| Tool | What it can do |
| --- | --- |
| `search_products` | Find items by category, feature, budget, and stock |
| `plan_budget_mission` | Deterministically build a stocked multi-product plan within a stated budget |
| `get_product_details` | Read authoritative price and specifications |
| `check_product_availability` | Verify current stock before an order |
| `place_order` | Persist an eligible low-value order or prepare a high-value approval plan |
| `checkout_cart` | Revalidate and order the signed-in user's persistent cart |
| `approve_purchase` | Revalidate and place the exact plan named by an approval token |
| `list_orders` | Read the current user's recent orders |
| `get_order_status` | Read status, ETA, and timeline |
| `cancel_order` | Enforce cancellation rules and update the order |
| `check_return_eligibility` | Check the delivered status, seven-day window, quantity, and replacement stock |
| `create_return_request` | Create a refund return or same-product replacement request |
| `get_return_request` | Track a return or exchange request |
| `search_faq` | Answer delivery, cancellation, return, payment and warranty questions |
| `summarize_product_reviews` | Summarize verified reviews stored in SQLite |
| `list_support_tickets` | Read the signed-in user's support history |
| `create_support_ticket` | Record an explicitly requested customer issue |
| `escalate_support_ticket` | Hand an exact ticket to the simulated human agent |
| `compare_products` | Compare catalog attributes and verified review evidence |
| `manage_cart` | Read or perform several explicit cart edits in one turn |
| `manage_preferences` | Inspect, save, disable, or erase user-controlled memory |
| `recommend_with_constraints` | Apply budget, brand, category, and delivery constraints |
| `prepare_order_modification` | Validate a reversible pre-dispatch change and request confirmation |
| `approve_order_modification` | Apply only an exact `MOD-...` confirmation |
| `get_proactive_assistance` | Detect seeded delivery delays and offer next actions |
| `reason_post_delivery_resolution` | Recommend refund, replacement, warranty, or support from policy state |

## Agent testing workspace

Open **Agent Insights** in the header after signing in. Each agent turn stores a
sanitized trace containing intent, tool names and sanitized arguments/results,
guardrail decisions, confidence/clarification state, exact runtime model,
fallback reason, latency, token usage, estimated cost, outcome, trace ID, and a
correlation ID. The correlation ID is returned with the chat response and the
trace is stored in SQLite under the signed-in user.

The viewer can replay a prior prompt in a deliberately read-only mode and can
download JSONL for DeepEval/pytest or CSV for analysis. `config.py`
is never included in traces or browser responses. The cost shown is an estimate
using the documented GPT-4.1 Nano text-token rates; Azure billing can differ.

The account dialog exposes the memory controls. Learners can inspect, edit,
disable, or erase budget, brand, location and urgency preferences. Delayed
seeded orders produce a proactive banner. Support intake validates an exact
owned order before ticket creation and accepts optional PNG/JPEG/WebP evidence
up to 1 MB through the API.

For a request such as “order the Sony headphones,” the flow is:

1. The browser sends natural language to `/api/chat`.
2. GPT-4.1 Nano decides which function tool is needed.
3. Python validates the tool arguments and checks the catalog/order store.
4. Python performs the action in SQLite and returns structured tool output.
5. The model turns that result into a short user-facing success or error message.
6. The UI shows an **Action log** so students can see the tool work without
   exposing private model reasoning.

Important guardrails are enforced in code as well as the prompt:

- Only an explicit `buy`, `order`, `place`, or `purchase` request can order.
- A clear cancellation command can cancel; “Can I cancel?” cannot.
- Prices, discounts, totals, user ID, stock, and order status come from Python.
- Ambiguous products/orders cause a clarifying question rather than a guess.
- Shipped or delivered orders cannot be cancelled.
- Every bundle and every purchase above ₹50,000 requires a persisted approval
  plan. Exactly ₹50,000 does not cross the threshold.
- Planning never creates an order. Approval requires a later message containing
  the exact `APR-...` token; stock and prices are checked again before commit.
- Approval tokens expire after 15 minutes and are bound to one chat session.
- Informational return/exchange questions never create a request.
- Only delivered items inside the seven-day window can be returned or exchanged.
- Exchange means a replacement of the same product, subject to replacement stock.
- Success is reported only after the JSON order store was updated.

### Human-in-the-loop purchase flow

For a mission such as `Build a gaming setup under 90000 with a laptop, mouse
and headphones`, Python chooses one in-stock product for each recognized need
using the requested strategy, calculates the authoritative total, and persists a
pending `shopping_plan`. No order exists yet. The response includes an
`approval_message`, for example `Approve APR-12AB34CD56`.

Send that exact command as a new chat message. VoltCart checks that the token is
pending, unexpired, belongs to the same session, and still has the same prices
and sufficient stock. Only then is one bundle order created. Reusing an approved
token returns the original order instead of creating a duplicate.

The same checkpoint applies to a single product above ₹50,000. Low-value,
single-product requests retain the immediate-order demo flow.

### Post-delivery service flow

`Can I return order ORD-DEMO-1001?` checks eligibility without changing data.
A direct return or exchange command creates a `Requested` service record. Refund
requests use `RET-...`; replacement exchanges use `EXC-...`. The original order
remains `Delivered`, and the request can be tracked independently in chat or via
the service-request read APIs.

## Project map

```text
ecommerce_agent_demo/
├── app.py                 Local HTTP server and JSON API routes
├── agent_service.py       GPT tool-calling loops, tool schemas, fallback
├── catalog.py             26 fixed electronics products and search
├── store.py               Thread-safe order, approval and stock logic
├── database.py            SQLite auth, carts, reviews and support persistence
├── config.py              Loads API settings and holds app policy/user settings
├── API_GUIDE.md           Postman and JSON API examples
├── postman/
│   └── VoltCart-Agent-API.postman_collection.json
├── start_demo.bat         Double-click launcher for Windows
├── static/
│   ├── index.html         Storefront and agent interface
│   ├── styles.css         Responsive styling
│   └── app.js             UI, API calls, filters, drawers and action cards
├── data/
│   └── voltcart.db        Created and seeded automatically on first run
└── tests/
    ├── test_store_and_agent.py
    └── test_customer_experience.py
```

Users, sessions, carts, preferences, orders, modifications, plans, idempotency
records, returns, reviews, FAQs, support tickets, evidence metadata, offers and
agent traces persist in `data/voltcart.db`. SQLite starts inside the
Python process automatically. Use **Reset demo** to restore teaching orders and
clear transient demo data.

## Run the tests

The normal pytest suite never calls the remote model and spends no API credits.

```powershell
python -m pip install -r requirements.txt
python -m pytest -v
```

They cover catalog search, deterministic budget missions, separate-turn and
session-bound approvals, high-value checkpoints, idempotency, permanent stock,
placement, tracking, cancellation, return eligibility, refund returns,
replacement exchanges, multi-action carts, memory isolation, order changes,
support intake/evidence, trace privacy, replay safety, API routes, and mocked
remote/local tool loops. Live Nano calls are an optional integration check and
are not run by pytest.

## Suggested student exercises

1. Write a DeepEval rubric for grounded recommendations using the JSONL export.
2. Compare the same trace in local and remote replay modes.
3. Add staff-only transitions from `Requested` to pickup/refund/replacement states.
4. Assert correlation IDs across a Playwright UI test and API response.
5. Run the included Postman collection and convert its checks into pytest tests.
6. Load-test read-only catalog APIs with JMeter while monitoring trace latency.

## Sharing checklist

Share the original `VoltCart-LangSmith-Student.zip`, which contains placeholder
keys and no saved database. Students extract it, edit `config.py`, and run
`start_demo.bat`. Do not redistribute a configured student folder containing
personal API keys or saved learner data. See `README.md` for full setup steps.

This is a local teaching demo, not a production checkout system. Authentication
and password hashing are implemented for learning, but there is no email/SMS
delivery, real identity verification or payment processing.
