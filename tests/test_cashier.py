"""Receipt allocation and fee snapshots through the authenticated cashier."""

from decimal import Decimal
import unittest
from copy import deepcopy

from platform_core.operations import billing, payment_terms, settlements
from platform_core.bootstrap import empty_workspace
from platform_core import access_policy


def money(value):
    return Decimal(str(value))


class Cashier(unittest.TestCase):
    day = "2026-11-24"

    def setUp(self):
        self.state = empty_workspace()
        self.state["residents"] = [dict(id="r", name="样例")]
        self.bill = self.new_bill("b", 50.01)
        self.set_rate(60)

    def new_bill(self, bid, amount):
        bill = dict(
            id=bid,
            residentId="r",
            month=self.day[:7],
            balance=amount,
            amount=amount,
            paid=0,
            endDate="2026-10-31",
            status="待缴费",
        )
        self.state["bills"].append(bill)
        return bill

    def set_rate(self, rate):
        payment_terms.configure(
            self.state,
            {"rates": dict.fromkeys(payment_terms.RATE_CHANNELS, rate)},
            self.day,
        )

    def test_card_gross_surplus_rounding_replay_and_next_invoice(self):
        data = dict(
            billId="b",
            amount="100.99",
            method="线下刷卡登记",
            channel="银联刷卡",
            carrySurplus=True,
            paymentRef="p1",
        )
        billing.pay(self.state, data, self.day)
        cash = self.state["payments"][0]
        advance = self.state["depositEntries"][0]
        self.assertEqual(
            (cash["amount"], cash["feeAmount"], cash["netAmount"]), (50.01, 0.30, 49.71)
        )
        self.assertEqual(
            (advance["amount"], advance["feeAmount"], advance["netAmount"]),
            (50.98, 0.31, 50.67),
        )
        self.assertEqual(
            (advance["receiptId"], self.bill["balance"]), (cash["receiptId"], 0)
        )
        self.assertEqual(cash["grossAmount"], 100.99)
        before = deepcopy(self.state)
        billing.pay(self.state, data, self.day)
        self.assertEqual(self.state, before)
        with self.assertRaises(ValueError):
            billing.pay(self.state, {**data, "amount": 101}, self.day)
        next_bill = self.new_bill("next", 80)
        billing.apply_deposit(self.state, self.state["deposits"][0], self.day)
        self.assertEqual(next_bill["balance"], 29.02)
        self.assertEqual(self.state["payments"][0]["method"], "预交金冲抵")
        self.assertEqual(
            sum(money(r["feeAmount"]) for r in (cash, advance)), money("0.61")
        )

    def test_online_prepaid_order_rate_snapshot_and_repeated_callback(self):
        p = dict(billId="b", channel="微信支付", amount=70, carrySurplus=True)
        settlements.create_order(self.state, p, self.day)
        settlements.create_order(self.state, p, self.day)
        (order,) = self.state["paymentOrders"]
        self.set_rate(100)
        payload = dict(
            merchantOrder=order["id"],
            transactionId="WX-simulated",
            channel="微信支付",
            amount=70,
            paidDate=self.day,
            source="local test",
        )
        receipt, changed = settlements.settle(
            self.state, payload, self.day, verification="渠道签名通知"
        )
        self.assertTrue(changed)
        self.assertEqual(
            (receipt["feeRateBps"], receipt["feeAmount"], receipt["netAmount"]),
            (60, 0.42, 69.58),
        )
        self.assertEqual(receipt["depositAmount"], 19.99)
        before = deepcopy(self.state)
        self.assertFalse(
            settlements.settle(
                self.state, payload, self.day, verification="渠道签名通知"
            )[1]
        )
        self.assertEqual(self.state, before)

    def test_deposit_first_and_no_dunning_for_settled_bill(self):
        account = billing.get_account(self.state, "r")
        account["amount"] = 51
        response = settlements.remind(
            self.state, dict(billId="b", channel="电话", note="核对欠款"), self.day
        )
        self.assertIn("无需催缴", response)
        self.assertFalse(self.bill.get("reminders"))
        self.assertEqual((self.bill["balance"], account["amount"]), (0, 0.99))

    def test_offline_wallet_and_signed_notification_share_one_receipt_in_either_order(
        self,
    ):
        for manual_first in (True, False):
            with self.subTest(manual_first=manual_first):
                self.setUp()
                p = dict(billId="b", channel="微信支付", amount=12)
                settlements.create_order(self.state, p, self.day)
                order = self.state["paymentOrders"][0]
                payload = dict(
                    **p,
                    merchantOrder=order["id"],
                    transactionId="local-wallet",
                    paidDate=self.day,
                )

                def notify():
                    return settlements.settle(
                        self.state,
                        {**payload, "source": "test"},
                        self.day,
                        verification="渠道签名通知",
                    )

                def manual():
                    return billing.pay(
                        self.state,
                        {**payload, "method": "线下登记", "paymentRef": "wallet-1"},
                        self.day,
                    )

                if manual_first:
                    manual()
                    self.assertFalse(notify()[1])
                else:
                    notify()
                    manual()
                self.assertEqual(
                    (
                        len(self.state["channelReceipts"]),
                        len(self.state["payments"]),
                        self.bill["balance"],
                    ),
                    (1, 1, 38.01),
                )

    def test_external_wallet_deposit_cannot_be_posted_again_as_bill_tender(self):
        p = dict(
            residentId="r",
            amount="60.01",
            method="线下登记",
            channel="支付宝",
            merchantOrder="outside",
            transactionId="original-transaction",
            paidDate=self.day,
        )
        billing.deposit(self.state, p, self.day)
        billing.deposit(self.state, p, self.day)
        self.assertEqual(len(self.state["depositEntries"]), 1)
        self.assertEqual(self.state["deposits"][0]["amount"], 10)
        with self.assertRaisesRegex(ValueError, "单独登记为预缴金"):
            settlements.settle(
                self.state,
                {**p, "billId": "b", "source": "test"},
                self.day,
                verification="财务人工核对",
            )

    def test_old_positive_prepayment_reconciles_before_order_issuance(self):
        account = billing.get_account(self.state, "r")
        account["amount"] = 10
        settlements.create_order(
            self.state, dict(billId="b", channel="微信支付", amount=50.01), self.day
        )
        self.assertEqual((self.bill["balance"], account["amount"]), (40.01, 0))
        self.assertFalse(self.state["paymentOrders"])

    def test_freeze_policy_and_accounting_boundaries(self):
        actor = dict(kind="staff", permissions=["finance"], facilityScope={})
        with self.assertRaises(PermissionError):
            access_policy.authorize(actor, "ops.paymentFees", {}, self.state)
        access_policy.authorize({"kind": "owner"}, "ops.paymentFees", {}, self.state)
        before = deepcopy(self.state)
        for invalid in (-1, 10001, True, "1.1"):
            with self.assertRaises(ValueError):
                self.set_rate(invalid)
            self.assertEqual(before, self.state)
        with self.assertRaises(ValueError):
            billing.pay(
                self.state,
                dict(billId="b", amount=12, method="线下刷卡登记", channel="现金"),
                self.day,
            )
        self.assertEqual(before, self.state)
