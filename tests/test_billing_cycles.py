from copy import deepcopy
import unittest

from platform_core.operations.billing import (
    generate_bill,
    pay,
    quote_bill,
    record_trial_fee,
)
from platform_core.operations.billing_cycles import pending_periods
from platform_core.operations.assistants import finance_suggestion


class BillingCyclesTest(unittest.TestCase):
    def setUp(self):
        self.resident = dict(
            id="r",
            name="甲",
            level="自理",
            bedId="b",
            admittedAt="2024-01-31",
            status="在住",
            billingDay=31,
        )
        self.state = dict(
            residents=[self.resident],
            beds=[dict(id="b", dailyRate=5)],
            bills=[],
            deposits=[],
            payments=[],
        )

    def quote(self, month, today, **kw):
        return quote_bill(self.state, {"residentId": "r", "month": month, **kw}, today)

    def test_short_month_returns_to_anchor_and_discharged_day_is_included(self):
        first = self.quote("2024-01", "2024-02-29")
        second = self.quote("2024-02", "2024-02-29")
        self.assertEqual(
            (first["startDate"], first["endDate"]), ("2024-01-31", "2024-02-28")
        )
        self.assertEqual(
            (second["billingDate"], second["endDate"]), ("2024-02-29", "2024-03-30")
        )
        with self.assertRaisesRegex(ValueError, "尚未"):
            self.quote("2024-03", "2024-03-27")
        self.resident.update(status="已退住", dischargedAt="2024-03-06")
        self.assertEqual(self.quote("2024-02", "2024-03-07")["serviceDays"], 7)
        with self.assertRaisesRegex(ValueError, "没有入住"):
            self.quote("2024-03", "2024-03-31")

    def test_short_first_cycle_two_issues_one_month_and_versioned_due_queue(self):
        self.resident.update(admittedAt="2026-11-11", billingDay=20)
        self.assertEqual(self.quote("2026-11", "2026-11-11")["endDate"], "2026-11-19")
        now = "2026-11-20"
        with self.assertRaisesRegex(ValueError, "两期"):
            self.quote("2026-11", now)
        payload = dict(residentId="r", month="2026-11", billingDate="2026-11-11")
        self.assertEqual(
            pending_periods(self.state, now)[0]["billingDate"], payload["billingDate"]
        )
        generate_bill(self.state, payload, now)
        with self.assertRaisesRegex(ValueError, "已有账单"):
            generate_bill(self.state, payload, now)
        self.assertEqual(pending_periods(self.state, now)[0]["billingDate"], now)
        generate_bill(self.state, {**payload, "billingDate": now}, now)
        self.assertEqual(pending_periods(self.state, now), [])
        self.assertEqual(self.state["bills"][0]["endDate"], "2026-12-19")

    def test_trial_fee_once_and_conversion_preserves_prepaid_nights(self):
        self.resident.update(
            admittedAt="2026-11-24",
            stayType="trial",
            trialEndsAt="2026-11-26",
            trialPrice=128.50,
        )
        self.resident.pop("billingDay")
        self.state["deposits"] = [dict(id="acct", residentId="r", amount=10.50)]
        record_trial_fee(self.state, self.resident, "2026-11-24")
        bill = self.state["bills"][0]
        self.assertEqual(
            (bill["kind"], bill["amount"], bill["balance"]), ("trial", 128.50, 118)
        )
        pay(self.state, {"billId": bill["id"], "amount": 118}, "2026-11-24")
        self.assertEqual(bill["status"], "已结清")
        with self.assertRaisesRegex(ValueError, "一次性费用"):
            record_trial_fee(self.state, self.resident, "2026-11-24")
        with self.assertRaisesRegex(ValueError, "试住"):
            self.quote("2026-11", "2026-11-24")
        self.assertEqual(pending_periods(self.state, "2026-11-24"), [])
        self.resident.update(
            formalizedAt="2026-11-25", stayType="formal", billingDay=25
        )
        self.assertEqual(pending_periods(self.state, "2026-11-25"), [])
        self.assertEqual(self.quote("2026-11", "2026-11-26")["startDate"], "2026-11-26")
        generate_bill(self.state, dict(residentId="r", month="2026-11"), "2026-11-26")
        self.assertEqual(len(self.state["bills"]), 2)
        self.assertIn("0 笔需复核", finance_suggestion(self.state, "2026-11-26")[2])

    def test_preserves_legacy_bills_without_changing_their_period_or_amount(self):
        self.resident.pop("billingDay")
        old = {
            "id": "old",
            "residentId": "r",
            "month": "2024-01",
            "amount": 32,
            "startDate": "2024-01-31",
            "endDate": "2024-01-31",
        }
        self.state["bills"] = [deepcopy(old)]
        with self.assertRaisesRegex(ValueError, "已有账单"):
            self.quote("2024-01", "2024-02-03")
        bill = self.quote("2024-02", "2024-02-03")
        self.assertEqual(
            (bill["startDate"], bill["endDate"]), ("2024-02-01", "2024-02-29")
        )
        self.assertEqual(self.state["bills"][0], old)
