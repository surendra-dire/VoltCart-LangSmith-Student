"""VoltCart local web server.

Run with: python app.py
Then open: http://127.0.0.1:8000
"""

from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
import sys
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from agent_service import AgentService
from catalog import CATEGORIES, PRODUCTS, get_product, search_products
from config import (
    APP_NAME,
    DEMO_USER,
    HOST,
    OPENAI_API_MODE,
    OPENAI_MODEL,
    PORT,
    PURCHASE_APPROVAL_THRESHOLD,
    RETURN_WINDOW_DAYS,
    STATIC_DIR,
    openai_is_configured,
)
from store import OrderStore
from observability import flush, status as tracing_status


STORE = OrderStore()
AGENT = AgentService(STORE)


class VoltCartHandler(BaseHTTPRequestHandler):
    server_version = "VoltCart/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        # Deliberately avoid request bodies and authorization data in logs.
        sys.stdout.write(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}\n")

    def _send_json(self, payload: object, status: int = HTTPStatus.OK, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_download(self, body: bytes, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _session_token(self) -> str:
        authorization = self.headers.get("Authorization", "")
        if authorization.casefold().startswith("bearer "):
            return authorization[7:].strip()
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get("voltcart_session")
        return morsel.value if morsel else ""

    def _current_user(self, required: bool = True) -> dict | None:
        user = STORE.database.user_for_session(self._session_token())
        if required and not user:
            self._send_json({"error": "Please sign in to continue."}, HTTPStatus.UNAUTHORIZED)
        return user

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length.") from exc
        if length <= 0:
            return {}
        # A 1 MB image becomes about 1.34 MB after base64 encoding.
        if length > 2_000_000:
            raise ValueError("Request body is too large.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request JSON must be an object.")
        return payload

    def _serve_static(self, requested_path: str) -> None:
        relative = "index.html" if requested_path in {"", "/"} else unquote(requested_path.lstrip("/"))
        if relative.startswith("static/"):
            relative = relative.removeprefix("static/")
        candidate = (STATIC_DIR / relative).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith(("text/", "application/javascript")) else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path in {"/api", "/api/"}:
            self._send_json(
                {
                    "name": f"{APP_NAME} local API",
                    "version": "1.0",
                    "base_url": f"http://{HOST}:{PORT}",
                    "documentation": "API_GUIDE.md",
                    "endpoints": [
                        {"method": "GET", "path": "/api/health", "purpose": "Check that the local server is running"},
                        {"method": "GET", "path": "/api/auth/me", "purpose": "Read the current signed-in user"},
                        {"method": "POST", "path": "/api/auth/register", "purpose": "Create a local learner account"},
                        {"method": "POST", "path": "/api/auth/login", "purpose": "Sign in and create an HTTP-only session"},
                        {"method": "POST", "path": "/api/auth/logout", "purpose": "End the current local session"},
                        {"method": "POST", "path": "/api/auth/forgot-password", "purpose": "Record a mock password-reset request"},
                        {"method": "GET", "path": "/api/config", "purpose": "Read safe demo and agent configuration"},
                        {"method": "GET", "path": "/api/products", "purpose": "Search and filter products"},
                        {"method": "GET", "path": "/api/products/{product_id}", "purpose": "Get one product"},
                        {"method": "GET", "path": "/api/orders", "purpose": "List demo-user orders"},
                        {"method": "GET", "path": "/api/orders/{order_id}", "purpose": "Get one order and its status"},
                        {"method": "GET", "path": "/api/cart", "purpose": "Read the signed-in user's persistent cart"},
                        {"method": "POST", "path": "/api/cart/items", "purpose": "Add or replace a cart quantity"},
                        {"method": "PATCH", "path": "/api/cart/items/{product_id}", "purpose": "Change a cart quantity"},
                        {"method": "DELETE", "path": "/api/cart/items/{product_id}", "purpose": "Remove a cart item"},
                        {"method": "GET/POST/DELETE", "path": "/api/preferences", "purpose": "Inspect, save, or erase visible agent memory"},
                        {"method": "GET", "path": "/api/proactive-assistance", "purpose": "Find simulated delayed orders"},
                        {"method": "GET", "path": "/api/support/tickets", "purpose": "Read the signed-in user's support tickets"},
                        {"method": "POST", "path": "/api/support/tickets", "purpose": "Create an owned support ticket"},
                        {"method": "POST", "path": "/api/support/tickets/{ticket_id}/escalate", "purpose": "Escalate to the simulated human agent"},
                        {"method": "POST", "path": "/api/support/tickets/{ticket_id}/attachments", "purpose": "Attach small PNG/JPEG/WebP evidence"},
                        {"method": "GET", "path": "/api/products/{product_id}/reviews", "purpose": "Read reviews and grounded summary data"},
                        {"method": "GET", "path": "/api/purchase-proposals/{approval_token}", "purpose": "Inspect a pending or approved plan"},
                        {"method": "GET", "path": "/api/service-requests", "purpose": "List return and exchange requests"},
                        {"method": "GET", "path": "/api/service-requests/{request_id}", "purpose": "Inspect one return or exchange request"},
                        {"method": "POST", "path": "/api/chat", "purpose": "Ask the GPT/local agent to search, order, track, or cancel"},
                        {"method": "POST", "path": "/api/chat/clear", "purpose": "Clear one agent conversation"},
                        {"method": "GET", "path": "/api/agent/traces", "purpose": "Inspect sanitized agent traces"},
                        {"method": "POST", "path": "/api/agent/traces/{trace_id}/replay", "purpose": "Replay a scenario in read-only mode"},
                        {"method": "GET", "path": "/api/agent/traces/export", "purpose": "Download JSON, JSONL, or CSV traces"},
                        {"method": "GET", "path": "/api/agent/metrics", "purpose": "Read cost, latency, token, and outcome metrics"},
                        {"method": "POST", "path": "/api/reset", "purpose": "Restore the classroom demo data"},
                    ],
                }
            )
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "app": APP_NAME, "database": "sqlite", "agent_mode": "remote" if openai_is_configured() else "local"})
            return
        if parsed.path == "/api/auth/me":
            user = self._current_user(required=False)
            self._send_json({"authenticated": bool(user), "user": user})
            return
        if parsed.path == "/api/config":
            user = self._current_user(required=False)
            with STORE.use_user(user):
                orders = STORE.list_orders(limit=50) if user else []
            self._send_json(
                {
                    "app_name": APP_NAME,
                    "model": OPENAI_MODEL,
                    "api_mode": OPENAI_API_MODE,
                    "agent_mode": "remote" if openai_is_configured() else "local",
                    "api_key_configured": openai_is_configured(),
                    "user": user,
                    "authentication_required": True,
                    "database": "SQLite",
                    "categories": CATEGORIES,
                    "product_count": len(PRODUCTS),
                    "order_count": len(orders),
                    "active_order_count": sum(1 for order in orders if order["status"] not in {"Delivered", "Cancelled"}),
                    "purchase_approval_threshold": PURCHASE_APPROVAL_THRESHOLD,
                    "return_window_days": RETURN_WINDOW_DAYS,
                }
            )
            return
        if parsed.path == "/api/products":
            query = parse_qs(parsed.query)
            max_price = None
            if query.get("max_price", [""])[0]:
                try:
                    max_price = int(query["max_price"][0])
                except ValueError:
                    self._send_json({"error": "max_price must be a whole number."}, HTTPStatus.BAD_REQUEST)
                    return
            try:
                limit = int(query.get("limit", ["26"])[0])
            except ValueError:
                self._send_json({"error": "limit must be a whole number."}, HTTPStatus.BAD_REQUEST)
                return
            in_stock_only = query.get("in_stock", ["false"])[0].casefold() == "true"
            products = search_products(
                query=query.get("search", [""])[0],
                category=query.get("category", [""])[0],
                max_price=max_price,
                in_stock_only=in_stock_only,
                limit=26 if in_stock_only else limit,
            )
            for product in products:
                product["available_stock"] = STORE.available_quantity(product["id"])
            if in_stock_only:
                products = [product for product in products if product["available_stock"] > 0][: max(1, min(limit, 26))]
            self._send_json({"products": products, "count": len(products)})
            return
        if parsed.path.startswith("/api/products/") and parsed.path.endswith("/reviews"):
            product_id = parsed.path.removeprefix("/api/products/").removesuffix("/reviews").strip("/")
            try:
                self._send_json({"review_summary": STORE.database.reviews(product_id)})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        if parsed.path.startswith("/api/products/"):
            product_id = parsed.path.removeprefix("/api/products/")
            product = get_product(product_id)
            if not product:
                self._send_json({"error": "Product not found."}, HTTPStatus.NOT_FOUND)
                return
            product["available_stock"] = STORE.available_quantity(product["id"])
            self._send_json({"product": product})
            return
        if parsed.path == "/api/orders":
            user = self._current_user()
            if not user:
                return
            query = parse_qs(parsed.query)
            status = query.get("status", [""])[0]
            with STORE.use_user(user):
                orders = STORE.list_orders(status=status, limit=50)
            self._send_json({"orders": orders, "count": len(orders)})
            return
        if parsed.path.startswith("/api/orders/"):
            user = self._current_user()
            if not user:
                return
            with STORE.use_user(user):
                order = STORE.get_order(parsed.path.removeprefix("/api/orders/"))
            if not order:
                self._send_json({"error": "Order not found."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"order": order})
            return
        if parsed.path.startswith("/api/purchase-proposals/"):
            user = self._current_user()
            if not user:
                return
            with STORE.use_user(user):
                proposal = STORE.get_purchase_proposal(parsed.path.removeprefix("/api/purchase-proposals/"))
            if not proposal:
                self._send_json({"error": "Purchase proposal not found."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"shopping_plan": proposal})
            return
        if parsed.path == "/api/service-requests":
            user = self._current_user()
            if not user:
                return
            query = parse_qs(parsed.query)
            with STORE.use_user(user):
                requests = STORE.list_service_requests(query.get("order_id", [""])[0])
            self._send_json({"service_requests": requests, "count": len(requests)})
            return
        if parsed.path.startswith("/api/service-requests/"):
            user = self._current_user()
            if not user:
                return
            with STORE.use_user(user):
                service_request = STORE.get_service_request(parsed.path.removeprefix("/api/service-requests/"))
            if not service_request:
                self._send_json({"error": "Service request not found."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"service_request": service_request})
            return
        if parsed.path == "/api/cart":
            user = self._current_user()
            if not user:
                return
            self._send_json({"cart": STORE.database.cart(user["id"], STORE.available_quantity)})
            return
        if parsed.path == "/api/preferences":
            user = self._current_user()
            if not user:
                return
            self._send_json({"preferences": STORE.database.preferences(user["id"])})
            return
        if parsed.path == "/api/proactive-assistance":
            user = self._current_user()
            if not user:
                return
            with STORE.use_user(user):
                assistance = STORE.proactive_assistance()
            self._send_json({"assistance": assistance, "count": len(assistance)})
            return
        if parsed.path == "/api/agent/metrics":
            user = self._current_user()
            if not user:
                return
            self._send_json({"metrics": STORE.database.trace_metrics(user["id"])})
            return
        if parsed.path == "/api/agent/traces/export":
            user = self._current_user()
            if not user:
                return
            query = parse_qs(parsed.query)
            export_format = query.get("format", ["json"])[0].casefold()
            traces = STORE.database.list_traces(user["id"], 200)
            if export_format == "jsonl":
                body = "\n".join(json.dumps(item, ensure_ascii=False) for item in traces).encode("utf-8")
                self._send_download(body, "application/x-ndjson; charset=utf-8", "voltcart-agent-traces.jsonl")
            elif export_format == "csv":
                stream = io.StringIO(newline="")
                fields = ["id", "correlation_id", "created_at", "intent", "mode", "model", "outcome", "confidence", "clarification", "latency_ms", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd"]
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows({key: item.get(key, "") for key in fields} for item in traces)
                self._send_download(stream.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", "voltcart-agent-traces.csv")
            else:
                self._send_download(json.dumps(traces, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8", "voltcart-agent-traces.json")
            return
        if parsed.path == "/api/agent/traces":
            user = self._current_user()
            if not user:
                return
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["50"])[0])
            except ValueError:
                limit = 50
            traces = STORE.database.list_traces(user["id"], limit)
            self._send_json({"traces": traces, "count": len(traces)})
            return
        if parsed.path.startswith("/api/agent/traces/"):
            user = self._current_user()
            if not user:
                return
            trace = STORE.database.get_trace(user["id"], parsed.path.removeprefix("/api/agent/traces/"))
            if not trace:
                self._send_json({"error": "Agent trace not found."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"trace": trace})
            return
        if parsed.path == "/api/support/tickets":
            user = self._current_user()
            if not user:
                return
            tickets = STORE.database.list_tickets(user["id"])
            self._send_json({"tickets": tickets, "count": len(tickets)})
            return
        if parsed.path.startswith("/api/support/tickets/"):
            user = self._current_user()
            if not user:
                return
            ticket = STORE.database.get_ticket(user["id"], parsed.path.removeprefix("/api/support/tickets/"))
            if not ticket:
                self._send_json({"error": "Support ticket not found."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ticket": ticket})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/auth/register":
                user = STORE.database.register(str(payload.get("name", "")), str(payload.get("email", "")), str(payload.get("phone", "")), str(payload.get("password", "")))
                token, user = STORE.database.login(user["email"], str(payload.get("password", "")))
                self._send_json({"ok": True, "user": user}, HTTPStatus.CREATED, {"Set-Cookie": f"voltcart_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800"})
                return
            if parsed.path == "/api/auth/login":
                token, user = STORE.database.login(str(payload.get("email", "")), str(payload.get("password", "")))
                self._send_json({"ok": True, "user": user}, extra_headers={"Set-Cookie": f"voltcart_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800"})
                return
            if parsed.path == "/api/auth/logout":
                STORE.database.logout(self._session_token())
                self._send_json({"ok": True}, extra_headers={"Set-Cookie": "voltcart_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})
                return
            if parsed.path == "/api/auth/forgot-password":
                STORE.database.forgot_password(str(payload.get("email", "")))
                self._send_json({"ok": True, "message": "If that demo account exists, a mock reset request has been recorded."})
                return
            if parsed.path == "/api/chat":
                user = self._current_user()
                if not user:
                    return
                message = str(payload.get("message", "")).strip()
                session_id = f"{user['id']}:{str(payload.get('session_id', 'demo-session'))[:80]}"
                message_id = str(payload.get("message_id", ""))[:120]
                with STORE.use_user(user):
                    result = AGENT.chat(message, session_id, message_id)
                self._send_json(result)
                return
            if parsed.path == "/api/chat/clear":
                user = self._current_user()
                if not user:
                    return
                session_id = f"{user['id']}:{str(payload.get('session_id', 'demo-session'))[:80]}"
                AGENT.clear_session(session_id)
                self._send_json({"ok": True})
                return
            if parsed.path.startswith("/api/agent/traces/") and parsed.path.endswith("/replay"):
                user = self._current_user()
                if not user:
                    return
                trace_id = parsed.path.removeprefix("/api/agent/traces/").removesuffix("/replay").strip("/")
                trace = STORE.database.get_trace(user["id"], trace_id)
                if not trace:
                    self._send_json({"error": "Agent trace not found."}, HTTPStatus.NOT_FOUND)
                    return
                prompt = str(payload.get("prompt", trace["user_message"])).strip()
                mode = str(payload.get("mode", "current")).casefold()
                if mode not in {"current", "local", "remote"}:
                    raise ValueError("Replay mode must be current, local, or remote.")
                session_id = f"{user['id']}:replay:{trace_id[:40]}"
                with STORE.use_user(user):
                    result = AGENT.chat(prompt, session_id, f"replay-{trace_id}", execution_mode=mode, read_only=True)
                result["replay"] = {"source_trace_id": trace_id, "read_only": True, "requested_mode": mode}
                self._send_json(result)
                return
            if parsed.path == "/api/preferences":
                user = self._current_user()
                if not user:
                    return
                preferences = STORE.database.update_preferences(user["id"], payload)
                self._send_json({"ok": True, "preferences": preferences})
                return
            if parsed.path == "/api/cart/items":
                user = self._current_user()
                if not user:
                    return
                product_id = str(payload.get("product_id", "")).strip().upper()
                quantity = payload.get("quantity", 1)
                if isinstance(quantity, bool) or not isinstance(quantity, int):
                    raise ValueError("Cart quantity must be a whole number between 1 and 5.")
                cart = STORE.database.set_cart_item(user["id"], product_id, quantity, STORE.available_quantity(product_id))
                self._send_json({"ok": True, "cart": STORE.database.cart(user["id"], STORE.available_quantity)}, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/support/tickets":
                user = self._current_user()
                if not user:
                    return
                order_id = str(payload.get("order_id", "")).strip().upper()
                if order_id:
                    with STORE.use_user(user):
                        if not STORE.get_order(order_id):
                            raise ValueError("That order was not found in the signed-in user's history.")
                ticket = STORE.database.create_ticket(user["id"], str(payload.get("category", "general")), str(payload.get("subject", "")), str(payload.get("description", "")), order_id, str(payload.get("priority", "Medium")))
                self._send_json({"ok": True, "ticket": ticket}, HTTPStatus.CREATED)
                return
            if parsed.path.startswith("/api/support/tickets/") and parsed.path.endswith("/escalate"):
                user = self._current_user()
                if not user:
                    return
                ticket_id = parsed.path.removeprefix("/api/support/tickets/").removesuffix("/escalate").strip("/")
                ticket = STORE.database.escalate_ticket(user["id"], ticket_id, str(payload.get("reason", "Customer requested escalation")))
                self._send_json({"ok": True, "ticket": ticket})
                return
            if parsed.path.startswith("/api/support/tickets/") and parsed.path.endswith("/attachments"):
                user = self._current_user()
                if not user:
                    return
                ticket_id = parsed.path.removeprefix("/api/support/tickets/").removesuffix("/attachments").strip("/")
                encoded = str(payload.get("content_base64", ""))
                try:
                    content = base64.b64decode(encoded, validate=True)
                except Exception as exc:
                    raise ValueError("Attachment content_base64 is invalid.") from exc
                attachment = STORE.database.add_ticket_attachment(user["id"], ticket_id, str(payload.get("file_name", "evidence.png")), str(payload.get("mime_type", "image/png")), content)
                self._send_json({"ok": True, "attachment": attachment, "ticket": STORE.database.get_ticket(user["id"], ticket_id)}, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/reset":
                user = self._current_user()
                if not user:
                    return
                with STORE.use_user(user):
                    orders = STORE.reset_demo()
                session_id = f"{user['id']}:{str(payload.get('session_id', 'demo-session'))[:80]}"
                AGENT.clear_session(session_id)
                self._send_json({"ok": True, "orders": orders, "message": "Demo orders and agent context were reset."})
                return
            self._send_json({"error": "Endpoint not found."}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # Keep a malformed classroom request from crashing the server.
            print(f"Request error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
            self._send_json({"error": "The server could not complete that request."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path.startswith("/api/cart/items/"):
                user = self._current_user()
                if not user:
                    return
                product_id = parsed.path.removeprefix("/api/cart/items/").strip().upper()
                quantity = payload.get("quantity")
                if isinstance(quantity, bool) or not isinstance(quantity, int):
                    raise ValueError("Cart quantity must be a whole number between 1 and 5.")
                STORE.database.set_cart_item(user["id"], product_id, quantity, STORE.available_quantity(product_id))
                self._send_json({"ok": True, "cart": STORE.database.cart(user["id"], STORE.available_quantity)})
                return
            self._send_json({"error": "Endpoint not found."}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/preferences":
            user = self._current_user()
            if not user:
                return
            self._send_json({"ok": True, "preferences": STORE.database.clear_preferences(user["id"])})
            return
        if parsed.path.startswith("/api/cart/items/"):
            user = self._current_user()
            if not user:
                return
            STORE.database.remove_cart_item(user["id"], parsed.path.removeprefix("/api/cart/items/"))
            self._send_json({"ok": True, "cart": STORE.database.cart(user["id"], STORE.available_quantity)})
            return
        self._send_json({"error": "Endpoint not found."}, HTTPStatus.NOT_FOUND)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), VoltCartHandler)
    mode = f"GPT agent ({OPENAI_MODEL})" if openai_is_configured() else "local demo agent (add a key in config.py for GPT)"
    print("\nVoltCart is ready")
    print(f"Open: http://{HOST}:{PORT}")
    print(f"Agent mode: {mode}")
    print(f"LangSmith: {tracing_status()}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping VoltCart...")
    finally:
        server.server_close()
        flush()


if __name__ == "__main__":
    main()
