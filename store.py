"""Thread-safe SQLite-backed commerce store used by the website and agent."""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from catalog import find_best_product, get_product
from database import CommerceDatabase
from config import (
    APPROVAL_TTL_MINUTES,
    DEMO_USER,
    MAX_BUNDLE_PRODUCTS,
    ORDERS_FILE,
    PURCHASE_APPROVAL_THRESHOLD,
    RETURN_WINDOW_DAYS,
)


CANCELLABLE_STATUSES = {"Confirmed", "Processing", "Packed"}
ACTIVE_STATUSES = {"Confirmed", "Processing", "Packed", "Shipped", "Out for delivery"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _empty_data(orders: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "orders": orders,
        "processed_actions": {},
        "purchase_proposals": {},
        "order_modifications": {},
        "service_requests": [],
    }


class OrderStore:
    def __init__(self, path: str | Path = ORDERS_FILE, seed_demo_data: bool = True):
        self.path = Path(path)
        self.seed_demo_data = seed_demo_data
        self._lock = threading.RLock()
        self._user_context = threading.local()
        self.database = CommerceDatabase(self.path, seed_demo_data=seed_demo_data)
        if self.database.read_state() is None:
            self._write_unlocked(_empty_data(self._seed_orders() if seed_demo_data else []))

    def current_user(self) -> dict[str, Any]:
        return getattr(self._user_context, "user", DEMO_USER)

    @contextmanager
    def use_user(self, user: dict[str, Any] | None):
        previous = getattr(self._user_context, "user", None)
        self._user_context.user = user or DEMO_USER
        try:
            yield self
        finally:
            if previous is None:
                self._user_context.__dict__.pop("user", None)
            else:
                self._user_context.user = previous

    def _read_unlocked(self) -> dict[str, Any]:
        data = self.database.read_state()
        if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
            data = _empty_data(self._seed_orders() if self.seed_demo_data else [])
            self._write_unlocked(data)
        data.setdefault("processed_actions", {})
        data.setdefault("purchase_proposals", {})
        data.setdefault("order_modifications", {})
        data.setdefault("service_requests", [])
        return data

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        self.database.write_state(data)

    @staticmethod
    def _item(product_id: str, quantity: int = 1) -> dict[str, Any]:
        product = get_product(product_id)
        if not product:
            raise ValueError(f"Unknown product {product_id}")
        return {
            "product_id": product["id"],
            "name": product["name"],
            "brand": product["brand"],
            "icon": product["icon"],
            "quantity": quantity,
            "unit_price": product["price"],
            "unit_mrp": product["mrp"],
            "line_total": product["price"] * quantity,
        }

    def _seed_orders(self) -> list[dict[str, Any]]:
        now = _now()
        seeds = [
            ("ORD-DEMO-1003", "WER-401", "Confirmed", now - timedelta(hours=1), now + timedelta(days=3)),
            ("ORD-DEMO-1002", "AUD-301", "Shipped", now - timedelta(days=2), now + timedelta(days=1)),
            ("ORD-DEMO-1001", "AUD-303", "Delivered", now - timedelta(days=8), now - timedelta(days=4)),
        ]
        orders: list[dict[str, Any]] = []
        for order_id, product_id, status, created, eta in seeds:
            item = self._item(product_id)
            history = [{"status": "Confirmed", "at": _iso(created)}]
            if status in {"Shipped", "Delivered"}:
                history.extend(
                    [
                        {"status": "Packed", "at": _iso(created + timedelta(hours=8))},
                        {"status": "Shipped", "at": _iso(created + timedelta(days=1))},
                    ]
                )
            if status == "Delivered":
                history.append({"status": "Delivered", "at": _iso(eta)})
            orders.append(
                {
                    "id": order_id,
                    "user_id": DEMO_USER["id"],
                    "items": [item],
                    "item_count": 1,
                    "subtotal": item["line_total"],
                    "savings": item["unit_mrp"] - item["unit_price"],
                    "total": item["line_total"],
                    "currency": "INR",
                    "status": status,
                    "cancellable": status in CANCELLABLE_STATUSES,
                    "created_at": _iso(created),
                    "updated_at": history[-1]["at"],
                    "estimated_delivery": eta.date().isoformat(),
                    "shipping_address": DEMO_USER["address"],
                    "payment_method": DEMO_USER["payment_method"],
                    "status_history": history,
                    "delayed": order_id == "ORD-DEMO-1002",
                    "delay_reason": "Carrier capacity disruption" if order_id == "ORD-DEMO-1002" else "",
                    "original_estimated_delivery": eta.date().isoformat(),
                }
            )
        return orders

    @staticmethod
    def _delivered_at(order: dict[str, Any]) -> datetime | None:
        delivered = next(
            (entry.get("at") for entry in reversed(order.get("status_history", [])) if entry.get("status") == "Delivered"),
            None,
        )
        try:
            return _parse_iso(delivered) if delivered else None
        except (TypeError, ValueError):
            return None

    def _decorate_order(self, order: dict[str, Any], requests: list[dict[str, Any]]) -> dict[str, Any]:
        related = [dict(item) for item in requests if item.get("order_id") == order.get("id")]
        delivered_at = self._delivered_at(order)
        deadline = delivered_at + timedelta(days=RETURN_WINDOW_DAYS) if delivered_at else None
        within_window = bool(order.get("status") == "Delivered" and deadline and _now() <= deadline)
        active_statuses = {"Requested", "Approved", "Pickup scheduled", "Replacement shipped"}
        remaining = 0
        for item in order.get("items", []):
            used = sum(
                int(request.get("quantity", 0))
                for request in related
                if request.get("product_id") == item.get("product_id") and request.get("status") in active_statuses
            )
            remaining += max(0, int(item.get("quantity", 0)) - used)
        order["service_requests"] = related
        order["return_deadline"] = deadline.date().isoformat() if deadline else None
        order["return_eligible"] = within_window and remaining > 0
        order["exchange_eligible"] = within_window and remaining > 0
        return order

    def _all_orders(self, include_all_users: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            data = self._read_unlocked()
            requests = list(data.get("service_requests", []))
            orders = [self._decorate_order(dict(order), requests) for order in data["orders"]]
        if not include_all_users:
            user_id = self.current_user()["id"]
            orders = [order for order in orders if order.get("user_id") == user_id]
        orders.sort(key=lambda order: order["created_at"], reverse=True)
        return orders

    def list_orders(self, status: str = "", limit: int = 20) -> list[dict[str, Any]]:
        orders = self._all_orders()
        if status:
            wanted = status.casefold()
            orders = [order for order in orders if order["status"].casefold() == wanted]
        return orders[: max(1, min(limit, 50))]

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        wanted = order_id.strip().upper()
        return next((order for order in self._all_orders() if order["id"].upper() == wanted), None)

    def find_orders_for_product(self, product_reference: str, active_only: bool = False) -> list[dict[str, Any]]:
        product = find_best_product(product_reference)
        reference = product["id"] if product else product_reference.strip().casefold()
        matches: list[dict[str, Any]] = []
        for order in self._all_orders():
            if active_only and order["status"] not in ACTIVE_STATUSES:
                continue
            for item in order["items"]:
                if item["product_id"] == reference or reference in item["name"].casefold():
                    matches.append(order)
                    break
        return matches

    def reserved_quantity(self, product_id: str) -> int:
        quantity = 0
        for order in self._all_orders(include_all_users=True):
            if order["status"] == "Cancelled":
                continue
            quantity += sum(item["quantity"] for item in order["items"] if item["product_id"] == product_id)
        return quantity

    def available_quantity(self, product_id: str) -> int:
        product = get_product(product_id)
        if not product:
            return 0
        # Classroom policy: inventory is inexhaustible so every scenario remains repeatable.
        return max(999, int(product.get("stock", 0)))

    @staticmethod
    def _consolidate_requested_items(requested_items: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
        if not requested_items:
            raise ValueError("At least one item is required.")
        consolidated: dict[str, int] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for requested in requested_items:
            product_id = str(requested.get("product_id", "")).strip().upper()
            product = get_product(product_id)
            if not product:
                raise ValueError(f"Product {product_id or '(missing id)'} was not found.")
            raw_quantity = requested.get("quantity", 1)
            if isinstance(raw_quantity, bool) or not str(raw_quantity).strip().isdigit():
                raise ValueError("Quantity must be a whole number.")
            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError) as exc:
                raise ValueError("Quantity must be a whole number.") from exc
            if quantity < 1 or quantity > 5:
                raise ValueError("Quantity must be between 1 and 5 for this demo.")
            consolidated[product_id] = consolidated.get(product_id, 0) + quantity
            if consolidated[product_id] > 5:
                raise ValueError("Total quantity for one product must be between 1 and 5.")
            metadata.setdefault(
                product_id,
                {
                    "need": str(requested.get("need", "")).strip(),
                    "reason": str(requested.get("reason", "")).strip(),
                },
            )
        if len(consolidated) > MAX_BUNDLE_PRODUCTS:
            raise ValueError(f"A bundle can contain at most {MAX_BUNDLE_PRODUCTS} different products.")
        return consolidated, metadata

    def _quote_unlocked(self, data: dict[str, Any], requested_items: list[dict[str, Any]]) -> dict[str, Any]:
        consolidated, metadata = self._consolidate_requested_items(requested_items)
        # Inventory is intentionally inexhaustible for repeatable classroom testing.

        items: list[dict[str, Any]] = []
        for product_id, quantity in consolidated.items():
            item = self._item(product_id, quantity)
            item.update({key: value for key, value in metadata[product_id].items() if value})
            items.append(item)
        subtotal = sum(item["line_total"] for item in items)
        catalog_savings = sum((item["unit_mrp"] - item["unit_price"]) * item["quantity"] for item in items)
        offers = self.database.active_offers(subtotal)
        offer = offers[0] if offers else None
        offer_discount = min(int(subtotal * offer["percent"] / 100), offer["max_discount"]) if offer else 0
        total = subtotal - offer_discount
        return {
            "items": items,
            "item_count": sum(item["quantity"] for item in items),
            "subtotal": subtotal,
            "catalog_savings": catalog_savings,
            "offer": offer,
            "offer_discount": offer_discount,
            "savings": catalog_savings + offer_discount,
            "delivery": 0,
            "total": total,
            "currency": "INR",
            "approval_required": len(items) > 1 or total > PURCHASE_APPROVAL_THRESHOLD,
        }

    def quote_order(self, requested_items: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            return self._quote_unlocked(self._read_unlocked(), requested_items)

    @staticmethod
    def _find_processed_order(data: dict[str, Any], idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        existing_id = data.setdefault("processed_actions", {}).get(idempotency_key)
        return next((item for item in data["orders"] if item["id"] == existing_id), None)

    def _build_order_unlocked(self, data: dict[str, Any], quote: dict[str, Any], approval_token: str = "") -> dict[str, Any]:
        now = _now()
        user = self.current_user()
        order = {
            "id": f"ORD-{now:%Y%m%d}-{uuid.uuid4().hex[:5].upper()}",
            "user_id": user["id"],
            "items": quote["items"],
            "item_count": quote["item_count"],
            "subtotal": quote["subtotal"],
            "savings": quote["savings"],
            "catalog_savings": quote.get("catalog_savings", quote["savings"]),
            "offer": quote.get("offer"),
            "offer_discount": quote.get("offer_discount", 0),
            "delivery": quote.get("delivery", 0),
            "total": quote["total"],
            "currency": "INR",
            "status": "Confirmed",
            "cancellable": True,
            "created_at": _iso(now),
            "updated_at": _iso(now),
            "estimated_delivery": (now + timedelta(days=3)).date().isoformat(),
            "shipping_address": user.get("address") or DEMO_USER["address"],
            "payment_method": DEMO_USER["payment_method"],
            "status_history": [{"status": "Confirmed", "at": _iso(now)}],
        }
        if approval_token:
            order["approval_token"] = approval_token
        data["orders"].append(order)
        return order

    def create_order(self, requested_items: list[dict[str, Any]], idempotency_key: str = "") -> dict[str, Any]:

        with self._lock:
            data = self._read_unlocked()
            processed = data.setdefault("processed_actions", {})
            existing = self._find_processed_order(data, idempotency_key)
            if existing:
                return existing
            quote = self._quote_unlocked(data, requested_items)
            if quote["approval_required"]:
                raise ValueError("Purchase approval is required for bundles or orders above ₹50,000.")
            order = self._build_order_unlocked(data, quote)
            if idempotency_key:
                processed[idempotency_key] = order["id"]
            self._write_unlocked(data)
            return order

    def prepare_purchase(
        self,
        requested_items: list[dict[str, Any]],
        mission: str,
        budget: int | None,
        session_id: str,
        originating_turn: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read_unlocked()
            processed = data.setdefault("processed_actions", {})
            if idempotency_key:
                existing_token = processed.get(idempotency_key)
                existing = data.setdefault("purchase_proposals", {}).get(existing_token)
                if existing:
                    return dict(existing)
            quote = self._quote_unlocked(data, requested_items)
            if budget is not None and quote["total"] > budget:
                raise ValueError(f"The proposed bundle costs ₹{quote['total']:,}, above the ₹{budget:,} budget.")
            now = _now()
            token = f"APR-{uuid.uuid4().hex[:10].upper()}"
            proposal = {
                "id": token,
                "token": token,
                "user_id": self.current_user()["id"],
                "session_id": session_id,
                "originating_turn": originating_turn,
                "mission": mission.strip() or "Agent-prepared purchase",
                "budget": budget,
                "items": quote["items"],
                "item_count": quote["item_count"],
                "subtotal": quote["subtotal"],
                "savings": quote["savings"],
                "catalog_savings": quote.get("catalog_savings", quote["savings"]),
                "offer": quote.get("offer"),
                "offer_discount": quote.get("offer_discount", 0),
                "delivery": quote.get("delivery", 0),
                "total": quote["total"],
                "remaining_budget": max(0, budget - quote["total"]) if budget is not None else None,
                "currency": "INR",
                "status": "Pending",
                "created_at": _iso(now),
                "expires_at": _iso(now + timedelta(minutes=APPROVAL_TTL_MINUTES)),
                "approved_at": None,
                "order_id": None,
                "shipping_address": self.current_user().get("address") or DEMO_USER["address"],
                "payment_method": DEMO_USER["payment_method"],
                "approval_message": f"Approve {token}",
            }
            data.setdefault("purchase_proposals", {})[token] = proposal
            if idempotency_key:
                processed[idempotency_key] = token
            self._write_unlocked(data)
            return dict(proposal)

    def get_purchase_proposal(self, token: str, session_id: str = "") -> dict[str, Any] | None:
        wanted = token.strip().upper()
        with self._lock:
            proposal = self._read_unlocked().setdefault("purchase_proposals", {}).get(wanted)
            if not proposal or proposal.get("user_id") != self.current_user()["id"] or (session_id and proposal.get("session_id") != session_id):
                return None
            return dict(proposal)

    def approve_purchase(
        self,
        token: str,
        session_id: str,
        current_turn: str,
        idempotency_key: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        wanted = token.strip().upper()
        with self._lock:
            data = self._read_unlocked()
            proposals = data.setdefault("purchase_proposals", {})
            proposal = proposals.get(wanted)
            if not proposal or proposal.get("user_id") != self.current_user()["id"] or proposal.get("session_id") != session_id:
                raise ValueError("That approval was not found in this conversation.")
            if proposal.get("status") == "Approved" and proposal.get("order_id"):
                existing = next((order for order in data["orders"] if order["id"] == proposal["order_id"]), None)
                if existing:
                    return dict(proposal), existing
            if proposal.get("status") != "Pending":
                raise ValueError(f"Approval {wanted} is {str(proposal.get('status', 'unavailable')).lower()}.")
            if current_turn and proposal.get("originating_turn") == current_turn:
                raise ValueError("Approval must be provided in a separate user message.")
            if _now() > _parse_iso(proposal["expires_at"]):
                proposal["status"] = "Expired"
                self._write_unlocked(data)
                raise ValueError("That approval expired. Ask the agent to prepare a fresh plan.")
            requested = [
                {
                    "product_id": item["product_id"],
                    "quantity": item["quantity"],
                    "need": item.get("need", ""),
                    "reason": item.get("reason", ""),
                }
                for item in proposal["items"]
            ]
            quote = self._quote_unlocked(data, requested)
            snapshot = [(item["product_id"], item["quantity"], item["unit_price"]) for item in proposal["items"]]
            current = [(item["product_id"], item["quantity"], item["unit_price"]) for item in quote["items"]]
            if current != snapshot or quote["total"] != proposal["total"]:
                proposal["status"] = "Invalid"
                self._write_unlocked(data)
                raise ValueError("A price changed. Ask the agent to prepare a fresh approval.")
            if proposal.get("budget") is not None and quote["total"] > proposal["budget"]:
                proposal["status"] = "Invalid"
                self._write_unlocked(data)
                raise ValueError("The plan no longer fits its budget.")
            order = self._build_order_unlocked(data, quote, approval_token=wanted)
            now = _iso(_now())
            proposal["status"] = "Approved"
            proposal["approved_at"] = now
            proposal["order_id"] = order["id"]
            if idempotency_key:
                data.setdefault("processed_actions", {})[idempotency_key] = order["id"]
            self._write_unlocked(data)
            return dict(proposal), order

    def _return_options_unlocked(self, data: dict[str, Any], order_id: str) -> dict[str, Any]:
        wanted = order_id.strip().upper()
        order = next(
            (item for item in data["orders"] if item["id"].upper() == wanted and item.get("user_id") == self.current_user()["id"]),
            None,
        )
        if not order:
            raise ValueError(f"Order {wanted} was not found.")
        delivered_at = self._delivered_at(order)
        deadline = delivered_at + timedelta(days=RETURN_WINDOW_DAYS) if delivered_at else None
        status_eligible = order.get("status") == "Delivered"
        within_window = bool(deadline and _now() <= deadline)
        active_requests = [
            request
            for request in data.setdefault("service_requests", [])
            if request.get("order_id") == order["id"] and request.get("status") not in {"Rejected", "Cancelled"}
        ]
        items: list[dict[str, Any]] = []
        for item in order.get("items", []):
            used = sum(int(request.get("quantity", 0)) for request in active_requests if request.get("product_id") == item["product_id"])
            remaining = max(0, int(item.get("quantity", 0)) - used)
            product = get_product(item["product_id"])
            replacement_stock = self.available_quantity(item["product_id"]) if product else 0
            items.append(
                {
                    **dict(item),
                    "remaining_quantity": remaining,
                    "refund_amount": item["unit_price"] * remaining,
                    "replacement_stock": replacement_stock,
                }
            )
        eligible = status_eligible and within_window and any(item["remaining_quantity"] > 0 for item in items)
        if not status_eligible:
            reason = f"Order {wanted} is {str(order.get('status', 'not delivered')).lower()}, so post-delivery service is unavailable."
        elif not within_window:
            reason = f"The {RETURN_WINDOW_DAYS}-day return window has ended."
        elif not any(item["remaining_quantity"] > 0 for item in items):
            reason = "All delivered quantities already have an active return or exchange request."
        else:
            reason = "Eligible for a refund return or same-product replacement."
        return {
            "ok": True,
            "eligible": eligible,
            "reason": reason,
            "window_days": RETURN_WINDOW_DAYS,
            "delivered_at": _iso(delivered_at) if delivered_at else None,
            "deadline": deadline.date().isoformat() if deadline else None,
            "items": items,
            "service_requests": [dict(request) for request in active_requests],
            "order": self._decorate_order(dict(order), data["service_requests"]),
        }

    def check_return_eligibility(self, order_id: str) -> dict[str, Any]:
        with self._lock:
            return self._return_options_unlocked(self._read_unlocked(), order_id)

    def create_return_request(
        self,
        order_id: str,
        product_id: str,
        quantity: int,
        resolution: str,
        reason: str,
        idempotency_key: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        resolution = resolution.strip().casefold()
        if resolution not in {"refund", "replacement"}:
            raise ValueError("Resolution must be refund or replacement.")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1 or quantity > 5:
            raise ValueError("Quantity must be a whole number between 1 and 5.")
        with self._lock:
            data = self._read_unlocked()
            processed = data.setdefault("processed_actions", {})
            if idempotency_key:
                existing_id = processed.get(idempotency_key)
                existing = next((item for item in data.setdefault("service_requests", []) if item["id"] == existing_id), None)
                if existing:
                    order = next(item for item in data["orders"] if item["id"] == existing["order_id"])
                    return dict(existing), self._decorate_order(dict(order), data["service_requests"])

            wanted_order = order_id.strip().upper()
            wanted_product = product_id.strip().upper()
            duplicate = next(
                (
                    item
                    for item in data.setdefault("service_requests", [])
                    if item.get("order_id", "").upper() == wanted_order
                    and item.get("product_id", "").upper() == wanted_product
                    and item.get("resolution") == resolution
                    and item.get("status") not in {"Rejected", "Cancelled"}
                ),
                None,
            )
            if duplicate:
                order = next(item for item in data["orders"] if item["id"] == duplicate["order_id"])
                return dict(duplicate), self._decorate_order(dict(order), data["service_requests"])

            options = self._return_options_unlocked(data, order_id)
            if not options["eligible"]:
                raise ValueError(options["reason"])
            product_id = product_id.strip().upper()
            selected = next((item for item in options["items"] if item["product_id"] == product_id), None)
            if not selected:
                raise ValueError("That product is not part of the delivered order.")
            if quantity > selected["remaining_quantity"]:
                raise ValueError(f"Only {selected['remaining_quantity']} delivered unit(s) remain eligible.")
            if resolution == "replacement" and selected["replacement_stock"] < quantity:
                raise ValueError("A same-product replacement is currently out of stock. A refund return is still available.")

            now = _now()
            request_id = f"{'RET' if resolution == 'refund' else 'EXC'}-{now:%Y%m%d}-{uuid.uuid4().hex[:5].upper()}"
            service_request = {
                "id": request_id,
                "type": "Return" if resolution == "refund" else "Exchange",
                "resolution": resolution,
                "status": "Requested",
                "user_id": self.current_user()["id"],
                "order_id": options["order"]["id"],
                "product_id": product_id,
                "product_name": selected["name"],
                "icon": selected.get("icon", "📦"),
                "quantity": quantity,
                "reason": reason.strip() or "Customer requested post-delivery service",
                "currency": "INR",
                "refund_amount": selected["unit_price"] * quantity if resolution == "refund" else 0,
                "pickup_date": (now + timedelta(days=2)).date().isoformat(),
                "replacement_eta": (now + timedelta(days=4)).date().isoformat() if resolution == "replacement" else None,
                "created_at": _iso(now),
                "updated_at": _iso(now),
                "status_history": [{"status": "Requested", "at": _iso(now)}],
            }
            data["service_requests"].append(service_request)
            raw_order = next(item for item in data["orders"] if item["id"] == service_request["order_id"])
            raw_order["updated_at"] = _iso(now)
            if idempotency_key:
                processed[idempotency_key] = request_id
            self._write_unlocked(data)
            return dict(service_request), self._decorate_order(dict(raw_order), data["service_requests"])

    def list_service_requests(self, order_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            requests = [
                dict(item)
                for item in self._read_unlocked().setdefault("service_requests", [])
                if item.get("user_id") == self.current_user()["id"]
            ]
        if order_id:
            wanted = order_id.strip().upper()
            requests = [item for item in requests if item.get("order_id", "").upper() == wanted]
        requests.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return requests[: max(1, min(limit, 50))]

    def get_service_request(self, request_id: str) -> dict[str, Any] | None:
        wanted = request_id.strip().upper()
        return next((item for item in self.list_service_requests() if item["id"].upper() == wanted), None)

    def cancel_order(self, order_id: str, reason: str = "Cancelled through shopping agent", idempotency_key: str = "") -> dict[str, Any]:
        wanted = order_id.strip().upper()
        with self._lock:
            data = self._read_unlocked()
            processed = data.setdefault("processed_actions", {})
            if idempotency_key and idempotency_key in processed:
                existing_id = processed[idempotency_key]
                existing = next((item for item in data["orders"] if item["id"] == existing_id), None)
                if existing:
                    return existing
            order = next(
                (item for item in data["orders"] if item["id"].upper() == wanted and item.get("user_id") == self.current_user()["id"]),
                None,
            )
            if not order:
                raise ValueError(f"Order {wanted} was not found.")
            if order["status"] not in CANCELLABLE_STATUSES:
                raise ValueError(f"Order {wanted} cannot be cancelled because it is already {order['status'].lower()}.")
            now = _iso(_now())
            order["status"] = "Cancelled"
            order["cancellable"] = False
            order["updated_at"] = now
            order["cancellation_reason"] = reason or "Cancelled through shopping agent"
            order["status_history"].append({"status": "Cancelled", "at": now})
            if idempotency_key:
                processed[idempotency_key] = order["id"]
            self._write_unlocked(data)
            return order

    def prepare_order_modification(self, order_id: str, address: str = "", quantity: int | None = None, delivery_slot: str = "") -> dict[str, Any]:
        with self._lock:
            data = self._read_unlocked()
            order = next((item for item in data["orders"] if item["id"] == order_id.strip().upper() and item.get("user_id") == self.current_user()["id"]), None)
            if not order:
                raise ValueError("Order not found.")
            if order["status"] not in {"Confirmed", "Processing", "Packed"}:
                raise ValueError(f"Order changes are unavailable after an order is {order['status'].lower()}.")
            changes: dict[str, Any] = {}
            if address.strip():
                if len(address.strip()) < 8:
                    raise ValueError("Please provide a complete delivery address.")
                changes["shipping_address"] = address.strip()[:200]
            if delivery_slot.strip():
                changes["delivery_slot"] = delivery_slot.strip()[:80]
            if quantity is not None:
                if order["status"] != "Confirmed":
                    raise ValueError("Quantity can only be changed while the order is Confirmed.")
                if len(order["items"]) != 1:
                    raise ValueError("Quantity changes require a single-item order.")
                if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 5:
                    raise ValueError("Quantity must be between 1 and 5.")
                changes["quantity"] = quantity
            if not changes:
                raise ValueError("Specify an address, quantity or delivery slot to change.")
            token = f"MOD-{uuid.uuid4().hex[:10].upper()}"
            proposal = {"id": token, "user_id": self.current_user()["id"], "order_id": order["id"], "status": "Pending", "changes": changes, "before": {"shipping_address": order.get("shipping_address"), "delivery_slot": order.get("delivery_slot", "Standard"), "quantity": order["items"][0]["quantity"] if len(order["items"]) == 1 else None}, "created_at": _iso(_now()), "approval_message": f"Confirm {token}"}
            data.setdefault("order_modifications", {})[token] = proposal
            self._write_unlocked(data)
            return proposal

    def approve_order_modification(self, token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._lock:
            data = self._read_unlocked()
            proposal = data.setdefault("order_modifications", {}).get(token.strip().upper())
            if not proposal or proposal.get("user_id") != self.current_user()["id"]:
                raise ValueError("Modification proposal not found.")
            order = next((item for item in data["orders"] if item["id"] == proposal["order_id"] and item.get("user_id") == self.current_user()["id"]), None)
            if not order:
                raise ValueError("Order not found.")
            if proposal["status"] == "Applied":
                return dict(proposal), order
            if order["status"] not in {"Confirmed", "Processing", "Packed"}:
                raise ValueError("The order progressed and can no longer be modified.")
            changes = proposal["changes"]
            if "shipping_address" in changes:
                order["shipping_address"] = changes["shipping_address"]
            if "delivery_slot" in changes:
                order["delivery_slot"] = changes["delivery_slot"]
            if "quantity" in changes:
                item = order["items"][0]
                item["quantity"] = changes["quantity"]
                item["line_total"] = item["unit_price"] * changes["quantity"]
                quote = self._quote_unlocked(data, [{"product_id": item["product_id"], "quantity": changes["quantity"]}])
                for key in ("item_count", "subtotal", "savings", "catalog_savings", "offer", "offer_discount", "delivery", "total"):
                    order[key] = quote.get(key, order.get(key))
            now = _iso(_now())
            order["updated_at"] = now
            order["status_history"].append({"status": "Order modified", "at": now, "changes": changes})
            proposal["status"] = "Applied"
            proposal["applied_at"] = now
            self._write_unlocked(data)
            return dict(proposal), order

    def proactive_assistance(self) -> list[dict[str, Any]]:
        return [
            {"type": "delivery_delay", "severity": "high", "order": order, "message": f"Order {order['id']} is delayed due to {order.get('delay_reason', 'a carrier issue')}.", "actions": ["track", "create_ticket", "escalate"]}
            for order in self.list_orders(limit=50)
            if order.get("delayed") and order.get("status") not in {"Delivered", "Cancelled"}
        ]

    def reset_demo(self) -> list[dict[str, Any]]:
        with self._lock:
            orders = self._seed_orders()
            self._write_unlocked(_empty_data(orders))
            self.database.reset_experience_data()
            return orders
