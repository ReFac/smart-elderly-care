from copy import deepcopy
import unittest

from platform_core.operations.discharge_settlement import settle
from platform_core.operations.admission_finance import use_security


class DischargeSettlementTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(
            residents=[
                dict(
                    id="r", name="测试档案", status="已退住", dischargedAt="2026-11-10"
                )
            ],
            deposits=[dict(residentId="r", amount=14.22)],
            bills=[
                dict(
                    id="deposit",
                    residentId="r",
                    kind="security",
                    amount=100,
                    paid=100,
                    balance=0,
                )
            ],
            payments=[dict(securityBillId="deposit", amount=25.51)],
        )
        self.actor = {"id": "cashier", "displayName": "测试经办人"}
        self.p = {
            "residentId": "r",
            "amount": "88.71",
            "method": "银行转账",
            "reference": "测试回单01",
        }

    def test_partial_security_offset_and_advance_are_returned_once(self):
        settle(self.state, self.p, self.actor, "2026-11-25")
        rec = self.state["dischargeSettlements"][0]
        self.assertEqual(
            (rec["security"], rec["advance"], rec["actorId"]), (74.49, 14.22, "cashier")
        )
        self.assertEqual(self.state["deposits"][0]["amount"], 0)
        self.assertEqual(self.state["bills"][0]["refundedSecurity"], 74.49)
        with self.assertRaises(ValueError):
            settle(self.state, {**self.p, "amount": "0"}, self.actor, "2026-11-25")
        self.assertEqual(len(self.state["dischargeSettlements"]), 1)
        person = {
            **self.state["residents"][0],
            "admissionTerms": {"securityMode": "overdue"},
            "admissionPayment": {"securityBillId": "deposit"},
        }
        self.assertIsNone(
            use_security(
                self.state,
                person,
                {"kind": "monthly", "billingDate": "2026-11-24", "balance": 1},
                "2026-11-25",
            )
        )

    def test_unpaid_changed_amount_or_missing_evidence_preserves_funds(self):
        for patch, change in [
            ({"amount": "74.49"}, {}),
            ({"reference": ""}, {}),
            ({}, {"balance": 12}),
        ]:
            state = deepcopy(self.state)
            state["bills"][0].update(change)
            with self.assertRaises(ValueError):
                settle(state, {**self.p, **patch}, self.actor, "2026-11-25")
            self.assertEqual(state["deposits"][0]["amount"], 14.22)
            self.assertNotIn("refundedSecurity", state["bills"][0])


class FinanceNavigationTests(unittest.TestCase):
    def test_spoken_pages_retain_exact_tab_and_dashboard_query(self):
        from platform_core.agents import chat_navigation as nav

        for title, view in [
            ("财务总览", "summary"),
            ("待收费", "unpaid"),
            ("月度账单确认", "due"),
            ("医疗费用", "medicalFees"),
            ("退住结算", "discharge"),
            ("收费记录", "receipts"),
            ("民政补贴申报材料", "subsidies"),
            ("日结报表", "daily"),
        ]:
            allowed = nav.visible({"kind": "owner", "permissions": []}, ["billing"])
            self.assertEqual(
                nav.direct_destination(
                    "打开" + title, allowed, {"billing": "navigate"}
                )["tab"],
                view,
            )
        plans = nav.visible({"kind": "owner", "permissions": []}, ["overview"])
        self.assertEqual(
            nav.direct_destination("打开运营看板", plans, {"overview": "navigate"})[
                "params"
            ],
            {"view": "cockpit"},
        )
        self.assertIsNone(
            nav.direct_destination("打开日结报表", plans, {"overview": "navigate"})
        )
