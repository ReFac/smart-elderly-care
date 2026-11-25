from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from platform_core.store import Store, TIMEZONE


class AdmissionFinanceTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(
            Path(directory.name) / "admission.sqlite3",
            lambda: datetime(2028, 1, 31, 12, tzinfo=TIMEZONE),
            initial_owner_password="admission-test-only",
        )
        self.token, _ = self.store.login("owner", "admission-test-only")
        self.command("care.register", {"name": "验收长辈"})
        state = self.state()
        self.rid = state["residents"][-1]["id"]
        self.bed = next(row["id"] for row in state["beds"] if row["status"] == "空闲")
        self.terms = dict(residentId=self.rid, bedId=self.bed, admittedAt="2028-01-31",
                          depositMonths=1, reminderDays=3, securityMode="overdue")

    def state(self):
        return self.store.snapshot(self.token)["data"]

    def command(self, action, payload):
        return self.store.execute(action, payload, self.store.version(self.token)["revision"], self.token)

    def preview(self, **extra):
        return self.store.admission_preview(self.token, dict(
            action="care.admit", payload={**self.terms, **extra},
            revision=self.store.version(self.token)["revision"],
        ))

    def finance(self):
        return {row["kind"]: row for row in self.state()["bills"] if row["residentId"] == self.rid}

    def test_monthly_quote_does_not_occupy_bed_or_write_before_review(self):
        quote = self.preview()
        self.assertEqual(quote["bill"]["startDate"], "2028-01-31")
        self.assertEqual(quote["bill"]["endDate"], "2028-02-28")
        self.assertEqual(quote["nextBillingDate"], "2028-02-29")
        self.assertEqual(quote["bill"]["amount"], quote["depositAmount"])
        self.assertEqual(self.finance(), {})
        rev = self.store.version(self.token)["revision"]
        with self.assertRaisesRegex(ValueError, "尚未结清"):
            self.command("care.admit", {**self.terms, "paymentMode": "standard"})
        self.assertEqual(self.store.version(self.token)["revision"], rev)
        self.assertEqual(self.finance(), {})

    def test_temporary_admission_is_linked_to_bills_and_clears_after_payment(self):
        self.command("care.admit", {**self.terms, "paymentMode": "temporary"})
        bills = self.finance()
        self.assertEqual(set(bills), {"monthly", "security"})
        self.assertEqual(bills["security"]["relatedBillId"], bills["monthly"]["id"])
        current = next(row for row in self.state()["residents"] if row["id"] == self.rid)
        self.assertEqual(current["admissionStatus"], "欠费临时入住")
        for bill in bills.values():
            self.command("ops.pay", {"billId": bill["id"], "amount": bill["amount"]})
        current = next(row for row in self.state()["residents"] if row["id"] == self.rid)
        self.assertEqual(current["admissionStatus"], "已结清")

    def test_manual_receipt_posts_both_bills_and_carries_surplus(self):
        quote = self.preview(paymentMode="offline")
        self.command("care.admit", {**self.terms, "paymentMode": "offline", "offlinePayment": {
            "amount": quote["dueAmount"] + 15, "method": "线下登记", "channel": "现金",
        }})
        self.assertTrue(all(row["balance"] == 0 for row in self.finance().values()))
        data = self.state()
        entries = [row for row in data["payments"] if row["residentId"] == self.rid]
        self.assertEqual(len({row["receiptId"] for row in entries}), 1)
        self.assertEqual(next(a["amount"] for a in data["deposits"] if a["residentId"] == self.rid), 15)
        with self.assertRaisesRegex(ValueError, "未入住档案"):
            self.command("care.admit", self.terms)
        self.assertEqual(len(self.finance()), 2)

    def test_admission_custom_bill_day_keeps_full_security_month(self):
        quote = self.preview(admittedAt="2028-01-30", billingDay=31)
        self.assertEqual(quote["bill"]["serviceDays"], 1)
        self.assertEqual(quote["depositAmount"], quote["bill"]["amount"] * 29)

    def test_finance_room_scope_and_reception_configuration(self):
        self.command("access.create", {
            "username": "local-reception", "kind": "staff", "role": "自定义",
            "displayName": "接待", "permissions": ["intake"], "password": "local-test-reception",
        })
        self.command("access.create", {
            "username": "local-finance", "kind": "staff", "role": "自定义",
            "displayName": "财务", "permissions": ["finance"], "password": "local-test-finance",
        })
        reception, _ = self.store.login("local-reception", "local-test-reception")
        finance, _ = self.store.login("local-finance", "local-test-finance")
        rev = self.store.version(reception)["revision"]
        with self.assertRaises(PermissionError):
            self.store.admission_preview(reception, {
                "action": "care.admit", "revision": rev, "payload": {**self.terms, "depositMonths": 0},
            })
        self.store.facility_policy = lambda db, user: {"roomIds": []} if user["username"] == "local-finance" else {}
        with self.assertRaises(PermissionError):
            self.store.bill_preview(finance, {"residentId": "r001", "month": "2027-12"}, rev)
