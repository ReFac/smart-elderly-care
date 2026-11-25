"""Only settled, adjacent renewal bills lengthen fixed terms."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from platform_core.operations import billing_lifecycle
from platform_core.store import Store, TIMEZONE


class ContractRenewalTests(TestCase):
    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.day("2028-01-01")
        self.store = Store(Path(root.name) / "renewal.sqlite3", initial_owner_password="renewal-fixture-only",
                           now=lambda: self.now)
        self.owner, _ = self.store.login("owner", "renewal-fixture-only")
        self.command("care.register", name="自动续住验收长辈")
        self.rid = self.state()["residents"][-1]["id"]
        self.bed = next(b["id"] for b in self.state()["beds"] if b["status"] == "空闲")

    def day(self, day):
        self.now = datetime.fromisoformat(day).replace(hour=12, tzinfo=TIMEZONE)

    def command(self, action, **payload):
        return self.store.execute(action, payload, self.store.version(self.owner)["revision"], self.owner)

    def state(self):
        return self.store.snapshot(self.owner)["data"]

    def resident(self):
        return next(r for r in self.state()["residents"] if r["id"] == self.rid)

    def bill(self, month, kind="monthly"):
        return next(b for b in self.state()["bills"]
                    if b["residentId"] == self.rid and b["kind"] == kind and b["month"] == month)

    def admit(self, end_date="2028-01-31", **options):
        self.command("care.admit", residentId=self.rid, bedId=self.bed, billingDay=1,
                     endDate=end_date, paymentMode="temporary", **options)
        self.pay(self.bill("2028-01"))

    def pay(self, bill, **options):
        self.command("ops.pay", billId=bill["id"], **{"amount": bill["balance"], **options})

    def issue(self, date):
        self.day(date)
        self.command("ops.bill", residentId=self.rid, billingDate=date, month=date[:7])
        return self.bill(date[:7])

    def test_partial_payment_replay_and_short_month_keep_one_renewal_per_bill(self):
        self.admit(depositMonths=0)
        self.assertEqual(self.resident()["renewalHistory"], [])
        bill = self.issue("2028-02-01")
        self.pay(bill, amount=1, paymentRef="part-one")
        self.assertEqual(self.resident()["endDate"], "2028-01-31")
        amount = self.bill("2028-02")["balance"]
        self.pay(bill, amount=amount, paymentRef="part-two")
        self.pay(bill, amount=amount, paymentRef="part-two")
        self.assertEqual(self.resident()["endDate"], "2028-02-29")
        self.assertEqual(len(self.resident()["renewalHistory"]), 1)
        self.assertEqual(self.bill("2028-02")["contractRenewal"]["previousEndDate"], "2028-01-31")
        march = self.issue("2028-03-01")
        self.command("ops.importReceipt", channel="微信支付", transactionId="renew-merchant-proof",
                     merchantOrder="renew-order", billId=march["id"], amount=march["balance"],
                     paidDate="2028-03-01", source="验收商户流水")
        self.assertEqual(self.resident()["endDate"], "2028-03-31")
        self.assertEqual(len(self.resident()["renewalHistory"]), 2)

    def test_later_invoice_does_not_skip_unpaid_months(self):
        self.admit()
        bill = self.issue("2028-04-01")
        self.pay(bill)
        self.assertEqual(self.resident()["endDate"], "2028-01-31")
        self.assertEqual(self.resident()["renewalHistory"], [])

    def test_security_withdrawal_notifies_without_renewing_contract(self):
        self.admit(securityMode="overdue")
        self.pay(self.bill("2028-01", "security"))
        self.issue("2028-02-01")
        self.day("2028-02-02")
        billing_lifecycle.tick(self.store)
        self.assertEqual(self.bill("2028-02")["balance"], 0)
        self.assertEqual(self.resident()["endDate"], "2028-01-31")
        self.assertEqual(self.resident()["renewalHistory"], [])
        self.assertCountEqual([n["kind"] for n in self.state()["billingNotices"] if n["residentId"] == self.rid],
                              ["contractExpired", "security"])

    def test_open_ended_terms_and_already_covered_months_do_not_extend(self):
        self.admit(end_date="2028-03-31")
        bill = self.issue("2028-02-01")
        self.pay(bill)
        self.assertEqual(self.resident()["endDate"], "2028-03-31")
        self.command("care.renew", residentId=self.rid, endDate="")
        march = self.issue("2028-03-01")
        self.pay(march)
        self.assertEqual(self.resident()["endDate"], "")
        self.assertEqual([r["source"] for r in self.resident()["renewalHistory"]], ["manual"])
