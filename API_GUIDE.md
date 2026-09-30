# VoltCart local API and Postman guide

Start the server first:

```powershell
python app.py
```

The base URL is `http://127.0.0.1:8000`. Open
<http://127.0.0.1:8000/api> to see the live endpoint index.

## Use the included Postman collection

1. In Postman, select **Import**.
2. Import `postman/VoltCart-Agent-API.postman_collection.json`.
3. Start `app.py`.
4. Run the collection from top to bottom.

The collection creates a fresh `message_id` before each request. It captures
`approval_token`, `approved_order_id`, `return_request_id`, and
`exchange_request_id` from successful responses. No OpenAI key is present in or
sent by Postman; the Python server reads its key from `config.py`.

This is a local classroom API. Sign in first; Postman keeps the returned
`voltcart_session` cookie and sends it to protected requests automatically. Do
not expose the app to a network or use it for real orders, payments or customer data.

## Authentication

Use the included **Sign in as demo user** request, or send:

```http
POST /api/auth/login
Content-Type: application/json

{"email":"aarav@voltcart.demo","password":"Demo@123"}
```

Registration uses `POST /api/auth/register` with `name`, `email`, `phone` and
`password`. Passwords need at least eight characters, uppercase, lowercase and
a number. `POST /api/auth/forgot-password` records a mock request; it does not
send email. `POST /api/auth/logout` invalidates the session.

## Main agent endpoint

### POST `/api/chat`

All writes intentionally go through the agent so the response shows which tools
were selected and what their structured results were.

```json
{
  "message": "Place an order for 1 x OnePlus Buds 3",
  "session_id": "postman-classroom-session",
  "message_id": "message-001"
}
```

Use one stable `session_id` for a conversation. Use a unique `message_id` for
each new user turn. Retrying an identical write with the same `message_id`
returns the original result rather than creating a duplicate.

The response envelope is:

```json
{
  "message": "User-facing reply",
  "mode": "remote",
  "model": "gpt-4.1-nano",
  "actions": [
    {"tool": "tool_name", "summary": "Visible action summary", "result": {"ok": true}}
  ],
  "entities": {},
  "warning": "Present only when a remote failure used local recovery",
  "trace": {"id":"TRC-...","correlation_id":"COR-...","intent":"order_management","latency_ms":850}
}
```

`mode` is `remote` when the configured model handled the turn and `local` when
the deterministic fallback handled it. Business rules are the same in both
modes.

## Budget mission and separate approval

Ask for at least two recognized needs and a numeric budget:

```json
{
  "message": "Build a gaming setup under 90000 with a laptop, mouse and headphones",
  "session_id": "postman-classroom-session",
  "message_id": "mission-001"
}
```

The `plan_budget_mission` tool deterministically chooses one in-stock product
for each need. Strategies supported by the tool are `balanced`, `lowest_cost`,
`best_rated`, and `maximum_savings`. The response contains
`entities.shopping_plan`:

```json
{
  "id": "APR-12AB34CD56",
  "token": "APR-12AB34CD56",
  "mission": "Gaming setup",
  "budget": 90000,
  "items": [
    {
      "product_id": "LAP-202",
      "name": "HP Victus 15 Gaming",
      "quantity": 1,
      "unit_price": 67990,
      "line_total": 67990,
      "need": "laptop",
      "reason": "Selected for laptop using the balanced strategy"
    }
  ],
  "item_count": 3,
  "subtotal": 85975,
  "savings": 17009,
  "total": 85975,
  "remaining_budget": 4025,
  "currency": "INR",
  "status": "Pending",
  "created_at": "2026-08-16T12:00:00Z",
  "expires_at": "2026-08-16T12:15:00Z",
  "approved_at": null,
  "order_id": null,
  "approval_message": "Approve APR-12AB34CD56"
}
```

The exact products and amounts depend on catalog pricing and active offers.
Classroom inventory is intentionally inexhaustible, so every learner can replay
the same flow. Planning does not create an order. Capture `token`, then send `approval_message` in a later
turn with a new `message_id`:

```json
{
  "message": "Approve APR-12AB34CD56",
  "session_id": "postman-classroom-session",
  "message_id": "mission-002"
}
```

Approval is accepted only when the token is pending, unexpired, belongs to the
same session, and was created in an earlier turn. Inventory policy, active offer,
price, total, and budget
are revalidated atomically. A successful response contains `entities.order`;
the order has an `approval_token` field. Reusing an approved token returns that
same order.

Every bundle requires approval. A single product requires approval only when
its authoritative total is **above** `₹50,000`; exactly `₹50,000` does not cross
the threshold. For example, `Order MacBook Air M2` returns a pending
`shopping_plan` instead of immediately placing the ₹84,990 order.

Inspect a plan directly:

```http
GET /api/purchase-proposals/APR-12AB34CD56
```

Response: `{"shopping_plan": {...}}`. Unknown tokens return HTTP 404 with an
`error` field.

## Return eligibility, refund returns, and exchanges

The seeded `ORD-DEMO-1001` is Delivered and is inside the seven-day demo return
window. An informational question checks eligibility without creating data:

```json
{
  "message": "Can I return order ORD-DEMO-1001?",
  "session_id": "postman-classroom-session",
  "message_id": "return-check-001"
}
```

The `check_return_eligibility` result includes:

```json
{
  "ok": true,
  "eligible": true,
  "reason": "Eligible for a refund return or same-product replacement.",
  "window_days": 7,
  "delivered_at": "2026-08-12T12:00:00Z",
  "deadline": "2026-08-19",
  "items": [
    {
      "product_id": "AUD-303",
      "remaining_quantity": 1,
      "refund_amount": 1299,
      "replacement_stock": 53
    }
  ],
  "service_requests": [],
  "order": {}
}
```

Dates and replacement stock vary with reset time and current demo state.

Create a refund return with a direct command:

```text
Return order ORD-DEMO-1001 because the earbuds are defective
```

Create a same-product replacement exchange:

```text
Exchange my delivered boAt Airdopes 141 for a replacement
```

Both use `create_return_request`. The chat response exposes the created record
as `entities.return_request`. Refund IDs start with `RET-`; exchange IDs start
with `EXC-`:

```json
{
  "id": "RET-20260816-A1B2C",
  "type": "Return",
  "resolution": "refund",
  "status": "Requested",
  "order_id": "ORD-DEMO-1001",
  "product_id": "AUD-303",
  "product_name": "boAt Airdopes 141",
  "quantity": 1,
  "reason": "the earbuds are defective",
  "currency": "INR",
  "refund_amount": 1299,
  "pickup_date": "2026-08-18",
  "replacement_eta": null,
  "created_at": "2026-08-16T12:00:00Z",
  "updated_at": "2026-08-16T12:00:00Z",
  "status_history": [{"status": "Requested", "at": "2026-08-16T12:00:00Z"}]
}
```

An exchange uses `type: "Exchange"`, `resolution: "replacement"`, a zero
refund amount, and a `replacement_eta`. This demo creates `Requested` records;
it does not include a staff workflow for advancing their status. The original
order remains Delivered.

Track in chat:

```text
Track return request RET-20260816-A1B2C for order ORD-DEMO-1001
```

Or use the read APIs:

```http
GET /api/service-requests?order_id=ORD-DEMO-1001
GET /api/service-requests/RET-20260816-A1B2C
```

Responses are `{"service_requests": [...], "count": 1}` and
`{"service_request": {...}}`. A second active return/exchange cannot claim the
same delivered quantity. The Postman collection resets between its return and
exchange demonstrations because the seeded order contains one unit.

## Read APIs

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api` | API discovery document |
| GET | `/api/health` | Check that Python is running |
| GET | `/api/auth/me` | Read the current session user |
| GET | `/api/config` | Safe model, policy, user, and catalog information |
| GET | `/api/products` | List/search/filter products |
| GET | `/api/products/{product_id}` | Get one product |
| GET | `/api/products/{product_id}/reviews` | Read grounded review data and summary fields |
| GET | `/api/cart` | Read the signed-in user's calculated cart |
| GET | `/api/orders` | List orders |
| GET | `/api/orders/{order_id}` | Read one decorated order and its service summary |
| GET | `/api/purchase-proposals/{approval_token}` | Read one pending/approved/expired/invalid plan |
| GET | `/api/service-requests?order_id={order_id}` | List return/exchange requests, optionally by order |
| GET | `/api/service-requests/{request_id}` | Read one return/exchange request |
| GET | `/api/support/tickets` | List the signed-in user's support tickets |
| GET | `/api/support/tickets/{ticket_id}` | Read one owned support ticket and messages |

Product query example:

```text
GET /api/products?search=wireless&category=Audio&max_price=10000&in_stock=true&limit=5
```

Order filtering example:

```text
GET /api/orders?status=Confirmed
```

`GET /api/config` includes `purchase_approval_threshold` and
`return_window_days`. It never returns the API key.

## Cart and support APIs

Cart writes validate the live stock and allow quantities 1 through 5:

```http
POST /api/cart/items                 {"product_id":"AUD-301","quantity":2}
PATCH /api/cart/items/AUD-301        {"quantity":1}
DELETE /api/cart/items/AUD-301
```

Support can be demonstrated through natural language in `/api/chat`, which is
the preferred agent lesson. Direct APIs are also available for Postman tests:

```http
POST /api/support/tickets
{"category":"damaged_item","subject":"Screen cracked","description":"The delivered screen arrived cracked.","order_id":"ORD-DEMO-1001","priority":"High"}

POST /api/support/tickets/SUP-.../escalate
{"reason":"Customer requested a human agent"}
```

The app checks order ownership before linking a support ticket. Review summaries
are grounded in the seeded SQLite reviews instead of invented customer feedback.

Evidence upload accepts a JSON base64 payload (PNG, JPEG, or WebP; maximum 1 MB):

```http
POST /api/support/tickets/SUP-.../attachments
{"file_name":"damage.png","mime_type":"image/png","content_base64":"iVBOR..."}
```

## Preference, proactive-assistance, trace and replay APIs

```http
GET /api/preferences
POST /api/preferences
{"enabled":true,"budget":80000,"favorite_brands":["Sony"],"excluded_brands":["Apple"],"delivery_location":"Bengaluru","delivery_urgency":"this week"}
DELETE /api/preferences

GET /api/proactive-assistance
GET /api/agent/traces?limit=50
GET /api/agent/traces/TRC-...
GET /api/agent/metrics
GET /api/agent/traces/export?format=jsonl
GET /api/agent/traces/export?format=csv
```

Replay is read-only even if the original prompt was transactional:

```http
POST /api/agent/traces/TRC-.../replay
{"mode":"current"}
```

`mode` may be `current`, `remote`, or `local`. Remote requires configured
credentials. Replay stores a new trace for side-by-side testing but code-level
guardrails deny order, cancellation, cart, preference, support, and modification
writes. Trace exports are sanitized and designed for DeepEval and pytest
assertions. They contain no API key, authorization cookie, password, address,
phone number, or email address.

## Utility APIs

Clear only one conversation context:

```http
POST /api/chat/clear
Content-Type: application/json

{"session_id":"postman-classroom-session"}
```

Restore the three seeded orders and clear plans, service requests, idempotency
records, and the named conversation:

```http
POST /api/reset
Content-Type: application/json

{"session_id":"postman-classroom-session"}
```

Response:

```json
{
  "ok": true,
  "orders": [{"id": "ORD-DEMO-1003"}, {"id": "ORD-DEMO-1002"}, {"id": "ORD-DEMO-1001"}],
  "message": "Demo orders and agent context were reset."
}
```

The actual `orders` entries contain their full order details. Purchase, approval,
cancellation, return, and exchange writes intentionally have no direct REST
endpoint; they go through `/api/chat` to demonstrate agent tool selection.
