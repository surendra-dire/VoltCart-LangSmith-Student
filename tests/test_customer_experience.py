from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent_service import AgentService
from database import CommerceDatabase
from store import OrderStore


class CustomerExperienceTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime = Path(__file__).parent / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.path = runtime / f"experience-{uuid.uuid4().hex}.db"
        self.store = OrderStore(self.path, seed_demo_data=True)
        self.db: CommerceDatabase = self.store.database

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    def test_registration_validation_duplicate_login_and_session(self) -> None:
        with self.assertRaisesRegex(ValueError, "uppercase"):
            self.db.register("Test Learner", "learner@example.test", "9876543210", "weakpass")
        user = self.db.register("Test Learner", "learner@example.test", "+91 98765 43210", "Learn@123")
        self.assertEqual(user["email"], "learner@example.test")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.db.register("Another Learner", "LEARNER@example.test", "9876543211", "Learn@123")
        token, signed_in = self.db.login("learner@example.test", "Learn@123")
        self.assertEqual(signed_in["id"], user["id"])
        self.assertEqual(self.db.user_for_session(token)["id"], user["id"])
        self.db.logout(token)
        self.assertIsNone(self.db.user_for_session(token))

    def test_cart_is_persistent_stock_validated_and_separate_per_user(self) -> None:
        aarav = self.db.login("aarav@voltcart.demo", "Demo@123")[1]
        priya = self.db.login("priya@voltcart.demo", "Demo@123")[1]
        self.db.set_cart_item(aarav["id"], "AUD-304", 2, self.store.available_quantity("AUD-304"))
        self.assertEqual(self.db.cart(aarav["id"])["item_count"], 2)
        self.assertEqual(self.db.cart(priya["id"])["item_count"], 0)
        reopened = CommerceDatabase(self.path, seed_demo_data=True)
        self.assertEqual(reopened.cart(aarav["id"])["item_count"], 2)
        with self.assertRaisesRegex(ValueError, "available"):
            self.db.set_cart_item(aarav["id"], "AUD-304", 5, 1)

    def test_orders_are_scoped_to_the_authenticated_user(self) -> None:
        aarav = self.db.login("aarav@voltcart.demo", "Demo@123")[1]
        priya = self.db.login("priya@voltcart.demo", "Demo@123")[1]
        with self.store.use_user(aarav):
            self.assertEqual(len(self.store.list_orders()), 3)
        with self.store.use_user(priya):
            self.assertEqual(self.store.list_orders(), [])
            order = self.store.create_order([{"product_id": "AUD-304", "quantity": 1}])
            self.assertEqual(order["user_id"], priya["id"])
        with self.store.use_user(aarav):
            self.assertNotIn(order["id"], {item["id"] for item in self.store.list_orders()})

    def test_support_ticket_creation_escalation_and_ownership(self) -> None:
        aarav = self.db.login("aarav@voltcart.demo", "Demo@123")[1]
        priya = self.db.login("priya@voltcart.demo", "Demo@123")[1]
        ticket = self.db.create_ticket(aarav["id"], "missing_item", "Missing charging cable", "The charging cable was not in the package.")
        self.assertEqual(ticket["status"], "Open")
        escalated = self.db.escalate_ticket(aarav["id"], ticket["id"], "Please connect me to a person")
        self.assertEqual(escalated["status"], "Escalated")
        self.assertIn("Human agent", escalated["assigned_to"])
        self.assertIsNone(self.db.get_ticket(priya["id"], ticket["id"]))

    def test_reviews_are_grounded_and_agent_can_summarize_and_create_ticket(self) -> None:
        summary = self.db.reviews("AUD-301")
        self.assertEqual(summary["review_count"], 3)
        self.assertEqual(summary["verified_count"], 3)
        aarav = self.db.login("aarav@voltcart.demo", "Demo@123")[1]
        agent = AgentService(self.store)
        with self.store.use_user(aarav), patch("agent_service.openai_is_configured", return_value=False):
            review = agent.chat("Summarize verified reviews for Sony WH-CH720N Headphones", "review-session", "review-1")
            ticket = agent.chat("Create a support ticket: my item is damaged and the screen is cracked", "ticket-session", "ticket-1")
        self.assertEqual(review["entities"]["review_summary"]["product"]["id"], "AUD-301")
        self.assertTrue(ticket["entities"]["support_draft"]["id"].startswith("DRF-"))

    def test_support_questions_do_not_mutate_without_explicit_intent(self) -> None:
        aarav = self.db.login("aarav@voltcart.demo", "Demo@123")[1]
        before = len(self.db.list_tickets(aarav["id"]))
        agent = AgentService(self.store)
        with self.store.use_user(aarav), patch("agent_service.openai_is_configured", return_value=False):
            answer = agent.chat("What should I do if an item arrives damaged?", "safe-session", "safe-1")
            escalation = agent.chat("Can a support ticket be escalated?", "safe-session", "safe-2")
        self.assertEqual(len(self.db.list_tickets(aarav["id"])), before)
        self.assertTrue(any(action["tool"] == "search_faq" for action in answer["actions"]))
        self.assertFalse(any(action["tool"] == "escalate_support_ticket" for action in escalation["actions"]))

    def test_agent_checks_out_cart_and_clears_it_after_commit(self) -> None:
        aarav = self.db.login("aarav@voltcart.demo", "Demo@123")[1]
        self.db.set_cart_item(aarav["id"], "AUD-304", 1, self.store.available_quantity("AUD-304"))
        agent = AgentService(self.store)
        with self.store.use_user(aarav), patch("agent_service.openai_is_configured", return_value=False):
            response = agent.chat("Checkout my cart", "cart-session", "cart-1")
        self.assertEqual(response["actions"][0]["tool"], "checkout_cart")
        self.assertTrue(response["entities"]["order"]["id"].startswith("ORD-"))
        self.assertEqual(self.db.cart(aarav["id"])["item_count"], 0)


if __name__ == "__main__":
    unittest.main()
