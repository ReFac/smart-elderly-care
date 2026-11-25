from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from platform_core.agents import chat_navigation
from platform_core.store import Store


class ReceivingTest(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / "care.db", initial_owner_password="synthetic-receiving-test")
        self.owner = self.store.login("owner", "synthetic-receiving-test")[0]

    def cmd(self, token, action, payload):
        return self.store.execute(action, payload, self.store.version(token)["revision"], token)

    def test_assistant_links_to_receiving_ledger_with_clinical_access(self):
        for role, expected in (("护士", True), ("护工", False)):
            with self.subTest(role=role):
                token = self.staff("receiving-" + str(expected).lower(), role)
                with closing(self.store.connect()) as db:
                    user = self.store.actor(db, token)
                pages = chat_navigation.visible(user, ["medications"])
                for question in ("家属送药在哪里登记", "打开药品交接台账"):
                    matches = chat_navigation.named(question, pages)
                    self.assertEqual(any(page.route == "medications" and page.tab == "receiving"
                                         for page in matches), expected)

    def test_signed_scoped_replay_and_no_implicit_medication_order(self):
        nurse = self.staff("nurse", "护士")
        helper = self.staff("helper", "护工")
        original = self.store.snapshot(self.owner)["data"]
        person = original["residents"][0]
        room = original["bedDirectory"][person["bedId"]]["roomId"]
        other = next(r for r in original["residents"] if r.get("bedId")
                     and original["bedDirectory"][r["bedId"]]["roomId"] != room)
        self.store.facility_policy = lambda db, user: {"roomIds": [room]} if user["displayName"] == "nurse" else {}
        action = "care.receiveMedication"
        payload = dict(residentId=person["id"], requestId=str(uuid4()), name="演示药品", specification="演示包装",
                       unit="瓶", source="家属交付", sender="测试交付人", quantity="1.25", lot="lot-01",
                       expiry="2030-01-01", operator="伪造经办", operatorId="spoof", nowLocal="2020-01-01")
        for override in ({"quantity": "NaN"}, {"quantity": "0"}, {"quantity": True}, {"name": ""}, {"unit": "invalid"}):
            with self.subTest(override), self.assertRaises(ValueError):
                self.cmd(nurse, action, {**payload, **override})
        with self.assertRaises(PermissionError):
            self.cmd(helper, action, payload)
        with self.assertRaises(PermissionError):
            self.cmd(nurse, action, {**payload, "residentId": other["id"]})
        self.cmd(nurse, action, payload)
        self.cmd(nurse, action, payload)
        with self.assertRaises(ValueError):
            self.cmd(nurse, action, {**payload, "quantity": "9"})
        self.cmd(self.owner, action, {**payload, "requestId": str(uuid4()), "residentId": other["id"]})
        docs = self.store.snapshot(nurse)["data"]["medicationReceipts"]
        self.assertEqual(len(docs), 1)
        receipt = docs[0]
        self.assertEqual(receipt["operator"], "nurse")
        self.assertNotEqual(receipt["operatorId"], "spoof")
        self.assertEqual(receipt["bedId"], person["bedId"])
        self.assertTrue(receipt["receivedAt"].startswith(self.store.now().date().isoformat()))
        self.assertEqual(receipt["quantity"], "1.25")
        self.assertEqual(self.store.snapshot(helper)["data"]["medicationReceipts"], [])
        self.assertEqual(self.store.snapshot(self.owner)["data"]["medications"], original["medications"])
        with closing(self.store.connect()) as db:
            self.assertTrue(db.execute("SELECT 1 FROM audit WHERE action=? AND residentId=? AND actorId=? AND room<>''",
                                       (action,person["id"],receipt["operatorId"])).fetchone())

    def staff(self, name, role):
        self.cmd(self.owner, "access.create", {"username":name, "displayName":name, "kind":"staff", "role":role,
                                              "password":"synthetic-receiving-test"})
        return self.store.login(name, "synthetic-receiving-test")[0]
