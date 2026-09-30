from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent_service import AgentService
from store import OrderStore


class AgenticProductionFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime = Path(__file__).parent / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.path = runtime / f"agentic-{uuid.uuid4().hex}.db"
        self.store = OrderStore(self.path, seed_demo_data=True)
        self.user = self.store.database.login("aarav@voltcart.demo", "Demo@123")[1]
        self.agent = AgentService(self.store)

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    def ask(self, message: str, session: str = "agentic") -> dict:
        with self.store.use_user(self.user), patch("agent_service.openai_is_configured", return_value=False):
            return self.agent.chat(message, session, f"msg-{uuid.uuid4().hex}")

    def test_inventory_is_intentionally_inexhaustible_for_classroom_replays(self) -> None:
        before = self.store.available_quantity("AUD-304")
        with self.store.use_user(self.user):
            for _ in range(12):
                self.store.create_order([{"product_id": "AUD-304", "quantity": 5}])
        self.assertGreaterEqual(before, 999)
        self.assertEqual(self.store.available_quantity("AUD-304"), before)

    def test_offer_is_applied_and_a_price_snapshot_is_kept_in_cart(self) -> None:
        self.store.database.set_cart_item(self.user["id"], "AUD-301", 1, self.store.available_quantity("AUD-301"))
        cart = self.store.database.cart(self.user["id"], self.store.available_quantity)
        quote = self.store.quote_order([{"product_id": "AUD-301", "quantity": 1}])
        self.assertEqual(cart["items"][0]["price_at_add"], cart["items"][0]["price"])
        self.assertEqual(quote["offer"]["code"], "VOLT10")
        self.assertGreater(quote["offer_discount"], 0)

    def test_grounded_comparison_and_constraint_recommendation(self) -> None:
        compared = self.ask("Compare Sony WH-CH720N, JBL Flip 6 and OnePlus Buds 3 for calls, travel and battery life")
        self.assertEqual(compared["actions"][0]["tool"], "compare_products")
        self.assertGreaterEqual(len(compared["entities"]["products"]), 2)
        self.assertTrue(all(item.get("evidence") for item in compared["entities"]["products"]))
        constrained = self.ask("Build a work-from-home setup under 80000 rupees excluding Apple with delivery this week")
        self.assertEqual(constrained["actions"][0]["tool"], "recommend_with_constraints")
        self.assertTrue(all(item["brand"] != "Apple" for item in constrained["entities"]["products"]))

    def test_conversational_cart_executes_multiple_changes(self) -> None:
        db = self.store.database
        db.set_cart_item(self.user["id"], "ACC-602", 1, self.store.available_quantity("ACC-602"))
        db.set_cart_item(self.user["id"], "LAP-202", 1, self.store.available_quantity("LAP-202"))
        response = self.ask("Add the cheaper Sony headphones, remove the mouse and change the laptop quantity to two")
        self.assertEqual(len(response["actions"]), 3)
        cart = db.cart(self.user["id"], self.store.available_quantity)
        quantities = {item["id"]: item["quantity"] for item in cart["items"]}
        self.assertNotIn("ACC-602", quantities)
        self.assertEqual(quantities["LAP-202"], 2)
        self.assertEqual(quantities["AUD-301"], 1)

    def test_preference_memory_is_visible_scoped_and_erasable(self) -> None:
        response = self.ask("Remember my budget is 80000 rupees, I prefer Sony, and exclude Apple")
        preferences = response["entities"]["preferences"]
        self.assertEqual(preferences["budget"], 80_000)
        self.assertEqual(preferences["favorite_brands"], ["Sony"])
        self.assertEqual(preferences["excluded_brands"], ["Apple"])
        cleared = self.ask("Forget everything in my preference memory")
        self.assertEqual(cleared["entities"]["preferences"]["favorite_brands"], [])

    def test_order_modification_requires_exact_confirmation_and_enforces_policy(self) -> None:
        prepared = self.ask("Change the delivery slot for order ORD-DEMO-1003 to Saturday")
        modification = prepared["entities"]["modification"]
        self.assertEqual(modification["status"], "Pending")
        approved = self.ask(modification["approval_message"])
        self.assertEqual(approved["entities"]["modification"]["status"], "Applied")
        rejected = self.ask("Change the delivery slot for order ORD-DEMO-1002 to Sunday")
        self.assertFalse(rejected["actions"][0]["result"]["ok"])

    def test_proactive_delay_and_resolution_reasoning(self) -> None:
        proactive = self.ask("Do any of my orders need proactive assistance?")
        self.assertGreaterEqual(len(proactive["entities"]["assistance"]), 1)
        resolution = self.ask("Should I get a refund or replacement for my delivered boAt Airdopes 141?")
        self.assertIn(resolution["entities"]["resolution"]["recommended_resolution"], {"replacement", "refund", "warranty_support"})

    def test_support_draft_collects_order_then_accepts_safe_evidence(self) -> None:
        drafted = self.ask("Create a support ticket because my delivered item is damaged", "support-flow")
        self.assertIn("support_draft", drafted["entities"])
        completed = self.ask("ORD-DEMO-1001", "support-flow")
        ticket = completed["entities"]["ticket"]
        attachment = self.store.database.add_ticket_attachment(self.user["id"], ticket["id"], "damage.png", "image/png", b"fake-png")
        self.assertEqual(attachment["size"], 8)
        with self.assertRaisesRegex(ValueError, "PNG, JPEG or WebP"):
            self.store.database.add_ticket_attachment(self.user["id"], ticket["id"], "notes.txt", "text/plain", b"unsafe")

    def test_trace_is_correlated_sanitized_exportable_and_measured(self) -> None:
        response = self.ask("Show products under 10000; contact learner@example.test")
        trace = response["trace"]
        self.assertTrue(trace["id"].startswith("TRC-"))
        self.assertTrue(trace["correlation_id"].startswith("COR-"))
        self.assertNotIn("learner@example.test", trace["user_message"])
        stored = self.store.database.get_trace(self.user["id"], trace["correlation_id"])
        self.assertEqual(stored["id"], trace["id"])
        self.assertEqual(self.store.database.trace_metrics(self.user["id"])["scenario_count"], 1)

    def test_replay_read_only_blocks_transactional_action(self) -> None:
        before = len(self.store.list_orders())
        with self.store.use_user(self.user), patch("agent_service.openai_is_configured", return_value=False):
            replay = self.agent.chat("Order OnePlus Buds 3", "replay", "replay-1", execution_mode="local", read_only=True)
        self.assertEqual(len(self.store.list_orders()), before)
        self.assertFalse(replay["actions"])
        self.assertIn({"check": "transactional_tools", "decision": "deny_read_only_replay"}, replay["trace"]["guardrails"])


if __name__ == "__main__":
    unittest.main()
