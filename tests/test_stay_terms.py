import unittest
from copy import deepcopy

from platform_core import care
from platform_core.bootstrap import OPERATIONS_COLLECTIONS
from platform_core.care.residency import active_card


class StayTermsTests(unittest.TestCase):
    def setUp(self):
        self.today = "2028-02-28"
        self.state = care.seed(self.today)
        self.state.update({k: [] for k in OPERATIONS_COLLECTIONS})
        care.apply(self.state, "care.register", {"name": "试住样例"}, self.today)
        self.person = self.state["residents"][-1]
        self.bed = next(b["id"] for b in self.state["beds"] if not b["residentId"])

    def apply(self, action, date=None, **payload):
        return care.apply(
            self.state,
            "care." + action,
            {"residentId": self.person["id"], **payload},
            date or self.today,
        )

    def test_admission_is_open_ended_and_old_dated_contract_can_be_renewed(self):
        self.apply("admit", bedId=self.bed)
        self.assertEqual(
            (
                self.person["stayType"],
                self.person["billingDay"],
                self.person["endDate"],
            ),
            ("formal", 28, ""),
        )
        self.apply("leave", startDate="2028-05-02", endDate="2028-05-10")
        with self.assertRaisesRegex(ValueError, "无需续住"):
            self.apply("renew", endDate="2028-06-30")
        existing = self.state["residents"][0]
        original = existing["endDate"]
        with self.assertRaises(ValueError):
            care.apply(
                self.state, "care.renew", {"residentId": existing["id"]}, self.today
            )
        self.assertEqual(existing["endDate"], original)
        care.apply(
            self.state,
            "care.renew",
            {"residentId": existing["id"], "endDate": ""},
            self.today,
        )
        self.assertEqual(existing["endDate"], "")
        self.assertNotIn("billingDay", existing)

    def test_trial_ends_on_third_day_and_converts_without_issuing_a_second_bed_card(
        self,
    ):
        self.state["trialPolicies"] = [{"id": "default", "days": 3, "fee": 180}]
        self.apply("admit", bedId=self.bed, stayType="trial")
        self.assertEqual(
            (self.person["trialEndsAt"], self.person["trialPrice"]), ("2028-03-01", 180)
        )
        self.assertNotIn("billingDay", self.person)
        self.assertEqual(self.state["bedMoves"][-1]["stayType"], "trial")
        self.assertEqual(len(self.state["bills"]), 1)
        card = active_card(self.state, self.person)
        previous = deepcopy(self.state)
        for action, payload in [
            ("discharge", {}),
            ("renew", {"endDate": "2029-01-01"}),
            ("confirmStay", {"billingDay": 32}),
        ]:
            with self.assertRaises(ValueError):
                self.apply(action, **payload)
        self.assertEqual(self.state, previous)
        self.apply("confirmStay", date="2028-03-01")
        self.assertEqual(
            (
                self.person["stayType"],
                self.person["formalizedAt"],
                self.person["admittedAt"],
                self.person["billingDay"],
            ),
            ("formal", "2028-03-01", self.today, 1),
        )
        self.assertEqual(active_card(self.state, self.person), card)
        self.assertEqual(len(self.state["bills"]), 1)
        with self.assertRaises(ValueError):
            self.apply("confirmStay", date="2028-03-01")

    def test_explicit_free_trial_and_end_keep_charge_and_archive_the_dossier(self):
        for overrides in (
            {},
            {"trialDays": 0, "trialPrice": 0},
            {"trialPrice": -1},
            {"trialPrice": "0.001"},
            {"billingDay": False, "trialPrice": 0},
        ):
            with self.assertRaises(ValueError):
                self.apply("admit", bedId=self.bed, stayType="trial", **overrides)
        self.assertEqual(self.person["status"], "未入住")
        self.apply("admit", bedId=self.bed, stayType="trial", trialPrice=0, trialDays=1)
        self.assertEqual(self.person["trialEndsAt"], self.today)
        with self.assertRaises(ValueError):
            self.apply("endTrial", reason="")
        self.apply("endTrial", reason="家属计划居家照护")
        self.assertEqual(
            (self.person["status"], self.person["bedId"], self.person["dischargeNote"]),
            ("已退住", "", "家属计划居家照护"),
        )
        self.assertTrue(self.person["archiveUntil"])
        self.assertEqual(
            [(b["kind"], b["amount"]) for b in self.state["bills"]], [("trial", 0)]
        )
        with self.assertRaises(ValueError):
            self.apply("confirmStay")

    def test_custom_billing_day_and_limited_contract(self):
        self.apply("admit", bedId=self.bed, billingDay="31", endDate="2028-06-20")
        self.assertEqual(self.person["billingDay"], 31)
        with self.assertRaises(ValueError):
            self.apply("leave", startDate=self.today, endDate="2028-06-21")
