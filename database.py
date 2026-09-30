"""SQLite persistence for the complete VoltCart classroom application."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from catalog import PRODUCTS, get_product
from config import DB_FILE


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000).hex()


def validate_password(password: str) -> None:
    if len(password) < 8 or not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must be at least 8 characters and include uppercase, lowercase and a number.")


class CommerceDatabase:
    """Small thread-safe-by-connection SQLite repository.

    Each method opens a short-lived connection. SQLite WAL mode lets classroom
    browser requests read concurrently while mutations remain transactional.
    """

    def __init__(self, path: str | Path = DB_FILE, seed_demo_data: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seed_demo_data = seed_demo_data
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                    phone TEXT NOT NULL, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
                    address TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS password_reset_requests (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL, category TEXT NOT NULL,
                    price INTEGER NOT NULL, mrp INTEGER NOT NULL, stock INTEGER NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cart_items (
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 5),
                    updated_at TEXT NOT NULL, PRIMARY KEY(user_id, product_id)
                );
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    order_id TEXT, category TEXT NOT NULL, subject TEXT NOT NULL, description TEXT NOT NULL,
                    priority TEXT NOT NULL, status TEXT NOT NULL, assigned_to TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ticket_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
                    sender TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS faq (
                    id TEXT PRIMARY KEY, topic TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, keywords TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id), user_name TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), title TEXT NOT NULL, body TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    enabled INTEGER NOT NULL DEFAULT 1, budget INTEGER, favorite_brands TEXT NOT NULL DEFAULT '[]',
                    excluded_brands TEXT NOT NULL DEFAULT '[]', use_cases TEXT NOT NULL DEFAULT '[]',
                    delivery_location TEXT NOT NULL DEFAULT '', delivery_urgency TEXT NOT NULL DEFAULT '',
                    previous_choices TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS support_drafts (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    order_id TEXT, category TEXT NOT NULL, subject TEXT NOT NULL, description TEXT NOT NULL,
                    missing_fields TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS support_attachments (
                    id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
                    file_name TEXT NOT NULL, mime_type TEXT NOT NULL, size INTEGER NOT NULL, content BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offers (
                    code TEXT PRIMARY KEY, description TEXT NOT NULL, percent INTEGER NOT NULL,
                    max_discount INTEGER NOT NULL, min_order INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS agent_traces (
                    id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    session_id TEXT NOT NULL, message_id TEXT NOT NULL, user_message TEXT NOT NULL,
                    intent TEXT NOT NULL, constraints_json TEXT NOT NULL, mode TEXT NOT NULL, model TEXT NOT NULL,
                    fallback_reason TEXT NOT NULL, confidence REAL NOT NULL, clarification INTEGER NOT NULL,
                    actions_json TEXT NOT NULL, guardrails_json TEXT NOT NULL, entities_json TEXT NOT NULL,
                    outcome TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL, estimated_cost_usd REAL NOT NULL, latency_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            cart_columns = {row[1] for row in db.execute("PRAGMA table_info(cart_items)").fetchall()}
            if "price_at_add" not in cart_columns:
                db.execute("ALTER TABLE cart_items ADD COLUMN price_at_add INTEGER NOT NULL DEFAULT 0")
            for product in PRODUCTS:
                db.execute(
                    """INSERT INTO products(id,name,brand,category,price,mrp,stock,payload) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,brand=excluded.brand,category=excluded.category,
                    price=excluded.price,mrp=excluded.mrp,stock=excluded.stock,payload=excluded.payload""",
                    (product["id"], product["name"], product["brand"], product["category"], product["price"], product["mrp"], product["stock"], json.dumps(product, ensure_ascii=False)),
                )
            if self.seed_demo_data:
                self._seed_users(db)
                self._seed_faq(db)
                self._seed_reviews(db)
                self._seed_tickets(db)
                db.executemany(
                    "INSERT OR IGNORE INTO offers VALUES(?,?,?,?,?,1)",
                    [
                        ("VOLT10", "10% classroom offer", 10, 3000, 5000),
                        ("AUDIO5", "5% off audio carts", 5, 1000, 2000),
                    ],
                )

    def _insert_user(self, db: sqlite3.Connection, user_id: str, name: str, email: str, phone: str, password: str, address: str) -> None:
        salt = secrets.token_bytes(16)
        db.execute(
            "INSERT OR IGNORE INTO users VALUES(?,?,?,?,?,?,?,?)",
            (user_id, name, email.casefold(), phone, _password_hash(password, salt), salt.hex(), address, _iso()),
        )

    def _seed_users(self, db: sqlite3.Connection) -> None:
        self._insert_user(db, "USR-1001", "Aarav Sharma", "aarav@voltcart.demo", "9876543210", "Demo@123", "42 Learning Lane, Bengaluru 560001")
        self._insert_user(db, "USR-1002", "Priya Nair", "priya@voltcart.demo", "9988776655", "Demo@123", "18 Innovation Road, Kochi 682001")

    def _seed_faq(self, db: sqlite3.Connection) -> None:
        rows = [
            ("FAQ-01", "delivery", "When will my order arrive?", "Confirmed orders normally arrive in 2-4 demo days. Shipped orders show an estimated delivery date in Orders.", "delivery arrive eta late delayed shipping"),
            ("FAQ-02", "cancellation", "Can I cancel an order?", "Confirmed, Processing and Packed orders can be cancelled. Shipped or Delivered orders cannot be cancelled.", "cancel cancellation order shipped packed"),
            ("FAQ-03", "returns", "What is the return policy?", "Delivered items can be returned or exchanged within 7 demo days when eligible.", "return refund exchange window policy"),
            ("FAQ-04", "payments", "Which payment methods are supported?", "This teaching app uses Demo cash on delivery and never charges a real payment method.", "payment cod card upi charge"),
            ("FAQ-05", "damaged", "What if an item is damaged?", "Ask Volt to create a damaged-item support ticket with the order ID and a short description.", "damaged broken defective support"),
            ("FAQ-06", "missing", "What if an item is missing?", "Report the missing item with its order ID. A support ticket can be assigned to the simulated human team.", "missing package item support"),
            ("FAQ-07", "warranty", "Do products include warranty?", "Warranty in this demo follows each manufacturer's simulated standard coverage; no real warranty is created.", "warranty coverage manufacturer"),
            ("FAQ-08", "agent", "What can the shopping agent do?", "Volt can search, compare, summarize reviews, order with safeguards, track, cancel, return and create or escalate support tickets.", "agent ai capability help"),
        ]
        db.executemany("INSERT OR IGNORE INTO faq VALUES(?,?,?,?,?)", rows)

    def _seed_reviews(self, db: sqlite3.Connection) -> None:
        templates = [
            (5, "Excellent value", "Performance is smooth, setup was easy and the offer price felt worthwhile."),
            (4, "Good everyday choice", "Reliable for daily use with solid build quality. Delivery and packaging were good."),
            (3, "Useful with a few trade-offs", "Core features work well, though battery or accessories could be better for heavy users."),
        ]
        names = ["Meera", "Kabir", "Ananya", "Rohan", "Ishita", "Dev"]
        for index, product in enumerate(PRODUCTS):
            for offset, (rating, title, body) in enumerate(templates):
                review_id = f"REV-{product['id']}-{offset + 1}"
                tailored = f"{body} For the {product['name']}, {product['short_spec'].lower()} stood out most."
                db.execute(
                    "INSERT OR IGNORE INTO reviews VALUES(?,?,?,?,?,?,?,?)",
                    (review_id, product["id"], names[(index + offset) % len(names)], rating, title, tailored, 1, _iso(_now() - timedelta(days=6 + index + offset * 9))),
                )

    def _seed_tickets(self, db: sqlite3.Connection) -> None:
        rows = [
            ("SUP-DEMO-1001", "USR-1001", "ORD-DEMO-1002", "delivery_delay", "Delivery update requested", "The shipped headphones have not moved since yesterday.", "Medium", "Open", "Support queue"),
            ("SUP-DEMO-1002", "USR-1001", "ORD-DEMO-1001", "damaged_item", "Earbud audio issue", "The right earbud has intermittent sound.", "High", "Escalated", "Human agent - Neha"),
            ("SUP-DEMO-1003", "USR-1002", None, "general", "Warranty clarification", "Asked about standard laptop warranty coverage.", "Low", "Resolved", "Support queue"),
        ]
        for ticket_id, user_id, order_id, category, subject, description, priority, status, assigned in rows:
            created = _iso(_now() - timedelta(days=2))
            db.execute("INSERT OR IGNORE INTO support_tickets VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ticket_id, user_id, order_id, category, subject, description, priority, status, assigned, created, created))

    # Existing order/approval/return state is stored atomically as JSON inside SQLite.
    def read_state(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM app_state WHERE id=1").fetchone()
            return json.loads(row[0]) if row else None

    def write_state(self, payload: dict[str, Any]) -> None:
        value = json.dumps(payload, ensure_ascii=False)
        with self.connect() as db:
            db.execute("INSERT INTO app_state(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (value,))

    @staticmethod
    def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in ("id", "name", "email", "phone", "address", "created_at")}

    def register(self, name: str, email: str, phone: str, password: str) -> dict[str, Any]:
        name, email, phone = name.strip(), email.strip().casefold(), re.sub(r"\D", "", phone)
        if len(name) < 2:
            raise ValueError("Please enter your full name.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Please enter a valid email address.")
        if not re.fullmatch(r"\d{10,15}", phone):
            raise ValueError("Phone number must contain 10 to 15 digits.")
        validate_password(password)
        user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
        salt = secrets.token_bytes(16)
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?,?,?,?)",
                    (user_id, name, email, phone, _password_hash(password, salt), salt.hex(), "Address not added", _iso()),
                )
                row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account with that email already exists.") from exc
        return self.public_user(row)

    def login(self, email: str, password: str) -> tuple[str, dict[str, Any]]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email.strip().casefold(),)).fetchone()
            if not row or not hmac.compare_digest(row["password_hash"], _password_hash(password, bytes.fromhex(row["password_salt"]))):
                raise ValueError("Incorrect email or password.")
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token, row["id"], _iso(), _iso(_now() + timedelta(days=7))))
            return token, self.public_user(row)

    def user_for_session(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self.connect() as db:
            row = db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?", (token, _iso())).fetchone()
            return self.public_user(row) if row else None

    def logout(self, token: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (token,))

    def forgot_password(self, email: str) -> None:
        with self.connect() as db:
            if db.execute("SELECT 1 FROM users WHERE email=?", (email.strip().casefold(),)).fetchone():
                db.execute("INSERT INTO password_reset_requests VALUES(?,?,?)", (f"RST-{uuid.uuid4().hex[:10].upper()}", email.strip().casefold(), _iso()))

    def cart(self, user_id: str, available: Any = None) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT product_id,quantity,updated_at,price_at_add FROM cart_items WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        items = []
        for row in rows:
            product = get_product(row["product_id"])
            if not product:
                continue
            quantity = int(row["quantity"])
            stock = int(available(product["id"])) if available else product["stock"]
            added_price = int(row["price_at_add"] or product["price"])
            items.append({**product, "quantity": quantity, "line_total": product["price"] * quantity, "available_stock": stock, "price_at_add": added_price, "price_changed": added_price != product["price"]})
        subtotal = sum(item["line_total"] for item in items)
        mrp_total = sum(item["mrp"] * item["quantity"] for item in items)
        return {"items": items, "item_count": sum(item["quantity"] for item in items), "subtotal": subtotal, "savings": mrp_total - subtotal, "delivery": 0, "total": subtotal, "currency": "INR"}

    def set_cart_item(self, user_id: str, product_id: str, quantity: int, available_stock: int) -> dict[str, Any]:
        product_id = product_id.strip().upper()
        if not get_product(product_id):
            raise ValueError("Product not found.")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1 or quantity > 5:
            raise ValueError("Cart quantity must be a whole number between 1 and 5.")
        if quantity > available_stock:
            raise ValueError(f"Only {available_stock} unit(s) are available.")
        with self.connect() as db:
            product = get_product(product_id)
            db.execute("INSERT INTO cart_items(user_id,product_id,quantity,updated_at,price_at_add) VALUES(?,?,?,?,?) ON CONFLICT(user_id,product_id) DO UPDATE SET quantity=excluded.quantity,updated_at=excluded.updated_at", (user_id, product_id, quantity, _iso(), product["price"]))
        return self.cart(user_id)

    def remove_cart_item(self, user_id: str, product_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (user_id, product_id.strip().upper()))

    def clear_cart(self, user_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM cart_items WHERE user_id=?", (user_id,))

    def preferences(self, user_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM user_preferences WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {"enabled": True, "budget": None, "favorite_brands": [], "excluded_brands": [], "use_cases": [], "delivery_location": "", "delivery_urgency": "", "previous_choices": []}
        result = dict(row)
        for key in ("favorite_brands", "excluded_brands", "use_cases", "previous_choices"):
            result[key] = json.loads(result[key] or "[]")
        result["enabled"] = bool(result["enabled"])
        return result

    def update_preferences(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.preferences(user_id)
        allowed = {"enabled", "budget", "favorite_brands", "excluded_brands", "use_cases", "delivery_location", "delivery_urgency", "previous_choices"}
        for key, value in updates.items():
            if key in allowed:
                current[key] = value
        if current.get("budget") is not None:
            current["budget"] = max(1000, min(int(current["budget"]), 1_000_000))
        for key in ("favorite_brands", "excluded_brands", "use_cases", "previous_choices"):
            current[key] = list(dict.fromkeys(str(item).strip() for item in (current.get(key) or []) if str(item).strip()))[:12]
        timestamp = _iso()
        with self.connect() as db:
            db.execute(
                """INSERT INTO user_preferences VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,budget=excluded.budget,
                favorite_brands=excluded.favorite_brands,excluded_brands=excluded.excluded_brands,
                use_cases=excluded.use_cases,delivery_location=excluded.delivery_location,
                delivery_urgency=excluded.delivery_urgency,previous_choices=excluded.previous_choices,updated_at=excluded.updated_at""",
                (user_id, int(bool(current.get("enabled", True))), current.get("budget"), json.dumps(current["favorite_brands"]), json.dumps(current["excluded_brands"]), json.dumps(current["use_cases"]), str(current.get("delivery_location", ""))[:160], str(current.get("delivery_urgency", ""))[:80], json.dumps(current["previous_choices"]), timestamp),
            )
        return self.preferences(user_id)

    def clear_preferences(self, user_id: str) -> dict[str, Any]:
        with self.connect() as db:
            db.execute("DELETE FROM user_preferences WHERE user_id=?", (user_id,))
        return self.preferences(user_id)

    def active_offers(self, subtotal: int) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM offers WHERE active=1 AND min_order<=? ORDER BY percent DESC", (subtotal,)).fetchall()]

    def save_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as db:
            db.execute(
                "INSERT INTO agent_traces VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (trace["id"], trace["correlation_id"], trace["user_id"], trace["session_id"], trace["message_id"], trace["user_message"], trace["intent"], json.dumps(trace.get("constraints", {}), ensure_ascii=False), trace["mode"], trace["model"], trace.get("fallback_reason", ""), float(trace["confidence"]), int(bool(trace["clarification"])), json.dumps(trace.get("actions", []), ensure_ascii=False), json.dumps(trace.get("guardrails", []), ensure_ascii=False), json.dumps(trace.get("entities", {}), ensure_ascii=False), trace["outcome"], int(trace.get("input_tokens", 0)), int(trace.get("output_tokens", 0)), int(trace.get("total_tokens", 0)), float(trace.get("estimated_cost_usd", 0)), int(trace.get("latency_ms", 0)), trace["created_at"]),
            )
        return self.get_trace(trace["user_id"], trace["id"])

    def _trace_row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for source, target in (("constraints_json", "constraints"), ("actions_json", "actions"), ("guardrails_json", "guardrails"), ("entities_json", "entities")):
            result[target] = json.loads(result.pop(source) or ("[]" if target in {"actions", "guardrails"} else "{}"))
        result["clarification"] = bool(result["clarification"])
        return result

    def get_trace(self, user_id: str, trace_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM agent_traces WHERE user_id=? AND (id=? OR correlation_id=?)", (user_id, trace_id, trace_id)).fetchone()
            return self._trace_row(row) if row else None

    def list_traces(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM agent_traces WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, max(1, min(limit, 200)))).fetchall()
            return [self._trace_row(row) for row in rows]

    def trace_metrics(self, user_id: str) -> dict[str, Any]:
        traces = self.list_traces(user_id, 200)
        count = len(traces)
        modes = {mode: sum(item["mode"] == mode for item in traces) for mode in ("remote", "local")}
        return {"scenario_count": count, "success_count": sum(item["outcome"] == "success" for item in traces), "clarification_count": sum(item["clarification"] for item in traces), "average_latency_ms": round(sum(item["latency_ms"] for item in traces) / count) if count else 0, "total_tokens": sum(item["total_tokens"] for item in traces), "estimated_cost_usd": round(sum(item["estimated_cost_usd"] for item in traces), 6), "modes": modes}

    def search_faq(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        tokens = {token for token in re.sub(r"[^a-z0-9]+", " ", query.casefold()).split() if len(token) > 2}
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM faq").fetchall()]
        ranked = []
        for row in rows:
            text = f"{row['topic']} {row['question']} {row['answer']} {row['keywords']}".casefold()
            score = sum(token in text for token in tokens)
            if score:
                ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in ranked[:limit]]

    def create_ticket(self, user_id: str, category: str, subject: str, description: str, order_id: str = "", priority: str = "Medium") -> dict[str, Any]:
        allowed = {"delivery_delay", "damaged_item", "missing_item", "payment", "return", "general"}
        category = category if category in allowed else "general"
        if len(subject.strip()) < 4 or len(description.strip()) < 8:
            raise ValueError("Please provide a short subject and description for the support ticket.")
        ticket_id = f"SUP-{_now():%Y%m%d}-{uuid.uuid4().hex[:5].upper()}"
        timestamp = _iso()
        priority = priority if priority in {"Low", "Medium", "High"} else "Medium"
        with self.connect() as db:
            db.execute("INSERT INTO support_tickets VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ticket_id, user_id, order_id.strip().upper() or None, category, subject.strip(), description.strip(), priority, "Open", "Support queue", timestamp, timestamp))
            db.execute("INSERT INTO ticket_messages(ticket_id,sender,message,created_at) VALUES(?,?,?,?)", (ticket_id, "Customer", description.strip(), timestamp))
        return self.get_ticket(user_id, ticket_id)

    def list_tickets(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM support_tickets WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()]

    def get_ticket(self, user_id: str, ticket_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM support_tickets WHERE id=? AND user_id=?", (ticket_id.strip().upper(), user_id)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["messages"] = [dict(item) for item in db.execute("SELECT sender,message,created_at FROM ticket_messages WHERE ticket_id=? ORDER BY id", (row["id"],)).fetchall()]
            result["attachments"] = [dict(item) for item in db.execute("SELECT id,file_name,mime_type,size,created_at FROM support_attachments WHERE ticket_id=? ORDER BY created_at", (row["id"],)).fetchall()]
            return result

    def escalate_ticket(self, user_id: str, ticket_id: str, reason: str) -> dict[str, Any]:
        ticket = self.get_ticket(user_id, ticket_id)
        if not ticket:
            raise ValueError("Support ticket not found.")
        if ticket["status"] == "Resolved":
            raise ValueError("A resolved ticket cannot be escalated.")
        timestamp = _iso()
        with self.connect() as db:
            db.execute("UPDATE support_tickets SET status='Escalated',priority='High',assigned_to='Human agent - Neha',updated_at=? WHERE id=?", (timestamp, ticket["id"]))
            db.execute("INSERT INTO ticket_messages(ticket_id,sender,message,created_at) VALUES(?,?,?,?)", (ticket["id"], "Volt AI", f"Escalated to a simulated human agent: {reason.strip() or 'Customer requested escalation'}", timestamp))
        return self.get_ticket(user_id, ticket["id"])

    def save_support_draft(self, user_id: str, category: str, subject: str, description: str, order_id: str = "") -> dict[str, Any]:
        missing = []
        if not order_id.strip():
            missing.append("order_id")
        if len(description.strip()) < 12:
            missing.append("description")
        draft_id = f"DRF-{uuid.uuid4().hex[:8].upper()}"
        timestamp = _iso()
        with self.connect() as db:
            db.execute("INSERT INTO support_drafts VALUES(?,?,?,?,?,?,?,?,?,?)", (draft_id, user_id, order_id.strip().upper() or None, category or "general", subject.strip() or "Customer support issue", description.strip(), json.dumps(missing), "Draft", timestamp, timestamp))
        return self.get_support_draft(user_id, draft_id)

    def get_support_draft(self, user_id: str, draft_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM support_drafts WHERE id=? AND user_id=?", (draft_id.strip().upper(), user_id)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["missing_fields"] = json.loads(result["missing_fields"] or "[]")
        return result

    def finalize_support_draft(self, user_id: str, draft_id: str, order_id: str) -> dict[str, Any]:
        draft = self.get_support_draft(user_id, draft_id)
        if not draft or draft["status"] != "Draft":
            raise ValueError("Support draft not found.")
        ticket = self.create_ticket(user_id, draft["category"], draft["subject"], draft["description"], order_id, "High" if draft["category"] in {"damaged_item", "missing_item"} else "Medium")
        with self.connect() as db:
            db.execute("UPDATE support_drafts SET status='Completed',order_id=?,missing_fields='[]',updated_at=? WHERE id=?", (order_id.strip().upper(), _iso(), draft["id"]))
        return ticket

    def add_ticket_attachment(self, user_id: str, ticket_id: str, file_name: str, mime_type: str, content: bytes) -> dict[str, Any]:
        ticket = self.get_ticket(user_id, ticket_id)
        if not ticket:
            raise ValueError("Support ticket not found.")
        allowed = {"image/png", "image/jpeg", "image/webp"}
        if mime_type not in allowed:
            raise ValueError("Evidence must be a PNG, JPEG or WebP image.")
        if not content or len(content) > 1_000_000:
            raise ValueError("Evidence image must be between 1 byte and 1 MB.")
        attachment_id = f"ATT-{uuid.uuid4().hex[:10].upper()}"
        with self.connect() as db:
            db.execute("INSERT INTO support_attachments VALUES(?,?,?,?,?,?,?)", (attachment_id, ticket["id"], file_name.strip()[:120] or "evidence", mime_type, len(content), content, _iso()))
        return {"id": attachment_id, "ticket_id": ticket["id"], "file_name": file_name.strip()[:120], "mime_type": mime_type, "size": len(content)}

    def reviews(self, product_id: str, limit: int = 8) -> dict[str, Any]:
        product = get_product(product_id)
        if not product:
            raise ValueError("Product not found.")
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM reviews WHERE product_id=? ORDER BY created_at DESC LIMIT ?", (product["id"], limit)).fetchall()]
        count = len(rows)
        average = round(sum(row["rating"] for row in rows) / count, 1) if count else 0
        distribution = {str(star): sum(row["rating"] == star for row in rows) for star in range(1, 6)}
        positives = ["value for money", "easy setup", "reliable everyday performance"]
        tradeoffs = ["heavy users may want stronger battery or bundled accessories"]
        return {"product": product, "review_count": count, "average_rating": average, "rating_distribution": distribution, "verified_count": sum(row["verified"] for row in rows), "common_praises": positives, "common_tradeoffs": tradeoffs, "reviews": rows}

    def reset_experience_data(self) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM cart_items")
            db.execute("DELETE FROM password_reset_requests")
            db.execute("DELETE FROM ticket_messages WHERE ticket_id NOT LIKE 'SUP-DEMO-%'")
            db.execute("DELETE FROM support_tickets WHERE id NOT LIKE 'SUP-DEMO-%'")
            db.execute("DELETE FROM support_drafts")
            db.execute("DELETE FROM agent_traces")
