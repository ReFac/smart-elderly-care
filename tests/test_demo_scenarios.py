import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from platform_core.store import Store
from platform_core.sample.scenarios import seed_scenarios


class DemoScenariosTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.now = datetime(2026, 11, 25, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.store = Store(Path(temp.name) / "demo.sqlite3", now=lambda: self.now, initial_data="demo",
                           initial_owner_password="test-scenarios-owner")
        self.owner, _ = self.store.login("owner", "test-scenarios-owner")

    def data(self):
        return self.store.snapshot(self.owner)["data"]

    def test_multiple_runs_and_family_view(self):
        with patch("platform_core.sample.scenarios.token_urlsafe", return_value="fictional-demo-test-password"):
            self.assertGreater(seed_scenarios(self.store, self.owner), 0)
        revision = self.store.version(self.owner)["revision"]
        self.assertEqual(0, seed_scenarios(self.store, self.owner))
        self.assertEqual(revision, self.store.version(self.owner)["revision"])

        state = self.data()
        people = {r["name"]: r for r in state["residents"]}
        self.assertEqual("未入住", people["邵清兰（演示）"]["status"])
        trial = people["夏月华（演示）"]
        self.assertEqual(("trial", 3, 240), (trial["stayType"], trial["trialDays"], trial["trialPrice"]))
        self.assertTrue(trial["bedId"])
        released = people["葛怀春（演示）"]
        self.assertEqual(("已退住", ""), (released["status"], released["bedId"]))
        self.assertIn("退住", [m["kind"] for m in state["bedMoves"] if m["residentId"] == released["id"]])
        self.assertEqual({"callback", "visit"}, {r["kind"] for r in state["visitBookings"]})
        self.assertTrue(all(r["status"] == "confirmed" for r in state["visitBookings"]))
        self.assertIn("已归档", {r["status"] for r in state["leadContacts"]})
        self.assertIn("回访", {r["kind"] for r in state["leadEvents"]})
        self.assertTrue(state["medicationReceipts"] and state["leaves"] and state["longCareEvents"])
        self.assertTrue(any(r.get("assigneeId") for r in state["handovers"]))
        self.assertTrue(any(r.get("kind") == "物资领用" for r in state["tasks"]))
        self.assertTrue(any("护理垫" in r["note"] for r in state["transactions"]))
        self.assertTrue(state["expenses"] and state["gatewayAlerts"])
        self.assertTrue(any(r.get("paymentRef") == "DEMO-PAYMENT-001" for r in state["payments"]))

        family, user = self.store.login("demo-family-jiang", "fictional-demo-test-password")
        self.assertEqual(people["江玉珊（演示）"]["id"], user["residentId"])
        family_view = self.store.snapshot(family)["data"]
        self.assertTrue(any(r["kind"] == "due" for r in family_view["billingNotices"]))
        with self.assertRaises(PermissionError):
            seed_scenarios(self.store, family)

    def test_retry_after_interruption_preserves_manual_updates(self):
        execute = self.store.execute

        def interrupt(action, *args, **kwargs):
            if action == "leads.book":
                raise RuntimeError("interrupted")
            return execute(action, *args, **kwargs)

        with patch.object(self.store, "execute", side_effect=interrupt), self.assertRaises(RuntimeError):
            seed_scenarios(self.store, self.owner)
        one = self.data()["leadContacts"][0]["id"]
        self.assertGreater(seed_scenarios(self.store, self.owner), 0)
        calls = [r for r in self.data()["leadEvents"] if r["leadId"] == one and r["kind"] == "回访"]
        self.assertEqual(1, len(calls))
        execute("leads.cancel", {"leadId": one, "kind": "callback", "feedback": "访客主动取消"},
                self.store.version(self.owner)["revision"], self.owner)
        self.now += timedelta(days=1)
        self.assertEqual(0, seed_scenarios(self.store, self.owner))
        bookings = [r for r in self.data()["visitBookings"] if r["leadId"] == one]
        self.assertEqual(["cancelled"], [r["status"] for r in bookings])
