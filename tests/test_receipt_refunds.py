from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from platform_core.agents import revenue
from platform_core.store import Store, TIMEZONE


class ReceiptRefundTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(
            Path(folder.name) / "finance.db",
            now=lambda: datetime(2026, 11, 24, 15, tzinfo=TIMEZONE),
            initial_owner_password="test-receipt-refunds",
        )
        self.owner = self.store.login("owner", "test-receipt-refunds")[0]
        bill = next(x for x in self.data()["bills"] if x["balance"] > 10)
        self.rid, self.bill = bill["residentId"], bill["id"]
        self.execute(
            "ops.pay",
            {
                "billId": self.bill,
                "amount": 8.22,
                "method": "线下登记",
                "channel": "现金",
            },
        )
        self.receipt = self.data()["payments"][0]["receiptId"]

    def data(self):
        return self.store.snapshot(self.owner)["data"]

    def execute(self, action, payload, token=None):
        token = token or self.owner
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def request(self, amount, request_id, receipt=None):
        self.execute(
            "ops.requestRefund",
            {
                "residentId": self.rid,
                "receiptId": receipt or self.receipt,
                "requestId": request_id,
                "amount": amount,
                "reason": "核对重复收款",
            },
        )
        return self.data()["refunds"][-1]["id"]

    def resolve(self, rid, ref):
        return self.execute(
            "ops.confirmRefund",
            {
                "residentId": self.rid,
                "refundId": rid,
                "verified": True,
                "reference": ref,
            },
        )

    def test_split_refunds_are_idempotent_and_reconciled_to_day(self):
        today = "2026-11-24"
        before = revenue.overview(self.data(), today)
        debt = next(b["balance"] for b in self.data()["bills"] if b["id"] == self.bill)
        first = self.request(3.21, "refund-1")
        self.assertEqual(first, self.request(3.21, "refund-1"))
        self.assertEqual(revenue.overview(self.data(), today), before)
        with self.assertRaises(ValueError):
            self.request(5.02, "overlap")
        self.resolve(first, "RF100")
        self.resolve(first, "RF100")
        second = self.request(5.01, "refund-2")
        with self.assertRaisesRegex(ValueError, "凭证"):
            self.resolve(second, "RF100")
        self.resolve(second, "RF101")
        with self.assertRaises(ValueError):
            self.request(0.01, "overrefunded")
        with self.assertRaises(ValueError):
            self.request(0.001, "sub-cent")
        data = self.data()
        self.assertEqual(len(data["refunds"]), 2)
        self.assertEqual(
            len([p for p in data["payments"] if p.get("refundOf") == self.receipt]), 2
        )
        after = revenue.overview(data, today)
        self.assertAlmostEqual(before["todayGross"] - after["todayGross"], 8.22)
        self.assertAlmostEqual(
            next(b["balance"] for b in data["bills"] if b["id"] == self.bill) - debt,
            8.22,
        )
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT residentId FROM audit WHERE action='ops.confirmRefund' LIMIT 1"
                ).fetchone()[0],
                self.rid,
            )

    def test_reserved_advance_can_be_released_without_cash_movement(self):
        person = next(
            p
            for p in self.data()["residents"]
            if p["status"] == "在住"
            and not any(
                b["residentId"] == p["id"] and b["balance"]
                for b in self.data()["bills"]
            )
        )
        self.rid = person["id"]
        self.execute(
            "ops.deposit",
            {
                "residentId": self.rid,
                "amount": 19.85,
                "method": "线下登记",
                "channel": "现金",
            },
        )
        advance = self.data()["depositEntries"][0]["receiptId"]

        def available():
            return next(
                r["amount"]
                for r in self.data()["deposits"]
                if r["residentId"] == self.rid
            )

        before = available()
        refund_id = self.request(12.10, "return-advance", advance)
        self.assertAlmostEqual(available(), before - 12.10)
        self.execute(
            "ops.cancelRefund", {"residentId": self.rid, "refundId": refund_id}
        )
        self.assertEqual(available(), before)
        complete = self.request(19.85, "full-advance", advance)
        self.resolve(complete, "RF200")
        self.assertAlmostEqual(available(), before - 19.85)
        reverse = self.data()["depositEntries"][0]
        self.assertEqual((reverse["refundOf"], reverse["amount"]), (advance, -19.85))

    def test_wrong_resident_and_accounts_without_finance_cannot_refund(self):
        with self.assertRaisesRegex(ValueError, "找不到退款申请"):
            self.resolve("missing-original-refund", "RF-MISSING")
        row = self.request(1, "r-one")
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.execute(
                "ops.confirmRefund",
                {
                    "residentId": "other",
                    "refundId": row,
                    "verified": True,
                    "reference": "X",
                },
            )
        self.execute(
            "access.create",
            {
                "kind": "staff",
                "role": "自定义",
                "username": "refund-care",
                "permissions": ["care"],
                "displayName": "照护员工",
                "password": "synthetic-care-password",
            },
        )
        staff = self.store.login("refund-care", "synthetic-care-password")[0]
        with self.assertRaises(PermissionError):
            self.execute(
                "ops.confirmRefund",
                {
                    "residentId": self.rid,
                    "refundId": row,
                    "verified": True,
                    "reference": "X",
                },
                staff,
            )
        self.assertFalse(self.store.snapshot(staff)["data"]["refunds"])
