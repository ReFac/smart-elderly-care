"""Verify onboarding through the real store for a site without demo residents."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import bootstrap
from platform_core.store import Store


class PilotOnboardingTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "pilot.sqlite3"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": ""}):
            self.store = Store(self.path, initial_data="empty")
        with closing(self.store.connect()) as db:
            initial = db.execute("SELECT password FROM storage_bootstrap").fetchone()[0]
        self.token, _ = self.store.login("owner", initial)

    def execute(self, action, **payload):
        self.store.execute(
            action, payload, self.store.version(self.token)["revision"], self.token
        )

    def test_empty_site_uses_six_registered_floors_and_can_admit_its_first_resident(
        self,
    ):
        snapshot = self.store.snapshot(self.token)["data"]
        for name in bootstrap.empty_workspace():
            self.assertEqual(snapshot[name], [], name)
        directory = self.store.facility_resource(self.token, "directory")
        floors = directory["buildings"][0]["floors"]
        self.assertEqual([f["number"] for f in floors], [1, 2, 3, 5, 6, 7])
        self.assertTrue(all(f["roomCount"] == 0 for f in floors))
        self.execute(
            "facility.addRoom",
            floorId=floors[0]["id"],
            number="101",
            ward="一区",
            bedCount=1,
        )
        rid = self.store.facility_resource(self.token, "search", q="１０１")["results"][
            0
        ]["roomId"]
        bed = self.store.facility_resource(self.token, "room", rid)["beds"][0]
        self.assertEqual(bed["status"], "空闲")
        self.execute("care.admit", name="试点验收", bedId=bed["id"])
        reopened = Store(self.path, initial_data="demo")
        data = reopened.snapshot(self.token)["data"]
        self.assertEqual([r["name"] for r in data["residents"]], ["试点验收"])
        self.assertEqual(len(data["beds"]), 1)
        self.assertEqual(data["inventory"], [])
        self.assertEqual(len(data["bedMoves"]), 1)
        self.assertEqual(
            reopened.facility_resource(self.token, "search", q="验")["results"][0][
                "roomId"
            ],
            rid,
        )

    def test_inventory_employee_can_open_first_item_and_trace_initial_stock(self):
        self.execute(
            "access.create",
            kind="staff",
            username="pilot-stock",
            displayName="仓储值班",
            password="pilot-fixture-stock",
            role="自定义",
            permissions=["inventory"],
        )
        token, _ = self.store.login("pilot-stock", "pilot-fixture-stock")

        def stock(action, **fields):
            self.store.execute(
                action, fields, self.store.version(token)["revision"], token
            )

        stock("ops.addItem", name="护理垫A", unit="包", minimum=3)
        data = self.store.snapshot(token)["data"]
        item = data["inventory"][0]
        self.assertEqual((item["quantity"], item["minimum"]), (0, 3))
        self.assertEqual(data["transactions"], [])
        with self.assertRaises(ValueError):
            stock("ops.addItem", name=" 护理垫Ａ ", unit="包", minimum=2)
        with self.assertRaises(ValueError):
            stock("ops.addItem", name="护理垫A", unit="盒", minimum=1, quantity=42)
        stock("ops.addItem", name="护理垫A", unit="盒", minimum=0)
        stock("ops.stock", itemId=item["id"], type="入库", quantity=12, note="期初盘点")
        stock("ops.stock", itemId=item["id"], type="出库", quantity=2, note="本班领用")
        reopened = Store(self.path)
        data = reopened.snapshot(token)["data"]
        self.assertEqual(data["inventory"][0]["quantity"], 10)
        self.assertEqual(
            [(t["type"], t["quantity"]) for t in data["transactions"]],
            [("出库", 2), ("入库", 12)],
        )
        self.assertIn(
            "ops.addItem", [r["action"] for r in reopened.activity(self.token)["rows"]]
        )
        self.execute(
            "access.create",
            kind="staff",
            username="pilot-front",
            displayName="前台",
            password="pilot-fixture-front",
            role="自定义",
            permissions=["intake"],
        )
        outsider, _ = self.store.login("pilot-front", "pilot-fixture-front")
        with self.assertRaises(PermissionError):
            reopened.execute(
                "ops.addItem",
                {"name": "护理垫", "unit": "箱", "minimum": 0},
                reopened.version(outsider)["revision"],
                outsider,
            )

    def test_reopening_untouched_empty_database_with_demo_default_preserves_empty_ledgers(
        self,
    ):
        original = self.store.facility_resource(self.token, "directory")
        reopened = Store(self.path)
        self.assertEqual(reopened.facility_resource(self.token, "directory"), original)
        self.assertEqual(reopened.version(self.token)["revision"], 0)
        data = reopened.snapshot(self.token)["data"]
        for name in bootstrap.empty_workspace():
            self.assertEqual(data[name], [], name)
