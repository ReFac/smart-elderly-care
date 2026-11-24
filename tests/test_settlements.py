"""Real commands through an institution workspace and locally signed merchant notifications."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from platform_core.store import Store, TIMEZONE
from platform_core.operations import channels
from platform_core.operations.billing import generate_bill

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    rsa = None


class Settlements(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.now = datetime(2026, 11, 24, 15, 0, tzinfo=TIMEZONE)
        with patch.dict(os.environ, {"NH_OWNER_PASSWORD": "local-finance-test"}):
            self.store = Store(self.root / "workspace.sqlite", now=lambda: self.now)
        self.user, _ = self.store.login("owner", "local-finance-test")
        self.bill = next(
            r
            for r in self.data()["bills"]
            if r["balance"] > 20 and r["endDate"] < "2026-11-24"
        )

    def data(self):
        return self.store.snapshot(self.user)["data"]

    def command(self, name, **fields):
        return self.store.execute(
            "ops." + name, fields, self.store.version(self.user)["revision"], self.user
        )

    def order(self, channel):
        self.command(
            "paymentOrder", billId=self.bill["id"], channel=channel, amount="12.20"
        )
        return self.data()["paymentOrders"][0]["id"]

    def test_order_link_and_external_voucher_never_double_count_across_channels_or_retries(
        self,
    ):
        num = self.order("支付宝")
        fields = dict(
            billId=self.bill["id"],
            channel="支付宝",
            merchantOrder=num,
            transactionId="M-113",
            amount="12.20",
            paidDate="2026-11-24",
            source="商户日结单第 16 行",
        )
        self.command("importReceipt", **fields)
        self.command("importReceipt", **fields)
        self.assertEqual(len(self.data()["channelReceipts"]), 1)
        self.assertEqual(self.data()["paymentOrders"][0]["status"], "已到账")
        self.assertEqual(self.data()["payments"][0]["amount"], 12.2)
        with self.assertRaises(ValueError):
            self.command("importReceipt", **{**fields, "merchantOrder": "elsewhere"})
        with self.assertRaises(ValueError):
            self.command("importReceipt", **{**fields, "verification": "渠道签名通知"})
        self.command(
            "remindBill", billId=self.bill["id"], channel="电话", note="家属已确认"
        )
        bill = next(r for r in self.data()["bills"] if r["id"] == self.bill["id"])
        self.assertEqual(bill["reminders"][0]["balance"], bill["balance"])
        self.command(
            "expense",
            category="餐饮",
            voucher="C-1",
            date="2026-11-20",
            payee="供货方",
            amount="81.82",
            note="午餐配料",
        )
        with self.assertRaises(ValueError):
            self.command(
                "expense",
                category="餐饮",
                voucher="C-1",
                date="2026-11-20",
                payee="供货方",
                amount="81.82",
                note="再次提交",
            )
        self.assertEqual(len(self.data()["expenses"]), 1)

    def test_report_keeps_immutable_submitted_versions_and_receipts(self):
        report = self.data()["reports"][0]
        metrics = report["serviceMetrics"]
        self.assertGreater(metrics["scheduledTasks"], 0)
        self.assertTrue(0 < metrics["servedResidents"] <= metrics["completedTasks"])
        self.command(
            "submitReport",
            reportId=report["id"],
            recipient="民政试点",
            submissionRef="S-01",
        )
        self.assertRaises(ValueError, self.command, "report", month=report["month"])
        self.command(
            "reportReceipt",
            reportId=report["id"],
            outcome="已退回",
            receiptRef="R-1",
            note="需补正",
        )
        self.command("report", month=report["month"])
        self.command(
            "submitReport",
            reportId=report["id"],
            recipient="民政试点",
            submissionRef="S-02",
        )
        self.command(
            "reportReceipt",
            reportId=report["id"],
            outcome="已受理",
            receiptRef="R-2",
            note="核对通过",
        )
        final = self.data()["reports"][0]
        self.assertEqual(final["submissions"][0]["snapshot"]["serviceMetrics"], metrics)
        self.assertEqual(
            set(metrics), {"scheduledTasks", "completedTasks", "servedResidents"}
        )
        self.assertEqual(
            [s["snapshot"]["version"] for s in final["submissions"]], [1, 2]
        )
        self.assertEqual(final["stage"], "已受理")
        frozen = self.store.report_version(self.user, report["id"], 1)
        self.assertEqual(frozen["dataset"], final["submissions"][0]["snapshot"])
        self.assertEqual(frozen["schemaVersion"], "ankang.civil.monthly.v1")
        with self.assertRaises(FileNotFoundError):
            self.store.report_version(self.user, report["id"], 3)
        self.store.execute(
            "access.create",
            {
                "kind": "family",
                "residentId": "r001",
                "username": "portal-read",
                "displayName": "已绑定账号",
                "password": "local-service-test",
            },
            self.store.version(self.user)["revision"],
            self.user,
        )
        portal, _ = self.store.login("portal-read", "local-service-test")
        with self.assertRaises(PermissionError):
            self.store.report_version(portal, report["id"], 1)

    @unittest.skipUnless(rsa, "optional cryptography package")
    def test_signed_notifications_both_channels_atomic_race_and_fifo_excess(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = self.root / "public.pem"
        pub.write_bytes(
            private.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        aes = os.urandom(32).hex()[:32].encode()
        secret = self.root / "key"
        secret.write_bytes(aes)

        def sign(value):
            return base64.b64encode(
                private.sign(value, padding.PKCS1v15(), hashes.SHA256())
            ).decode()

        config = dict(
            NH_WXPAY_PUBLIC_KEY_FILE=str(pub),
            NH_WXPAY_PUBLIC_KEY_ID="test-key",
            NH_WXPAY_V3_KEY_FILE=str(secret),
            NH_WXPAY_APP_ID="test-wx",
            NH_WXPAY_MERCHANT_ID="test-merchant",
            NH_ALIPAY_PUBLIC_KEY_FILE=str(pub),
            NH_ALIPAY_APP_ID="test-ali",
            NH_ALIPAY_SELLER_ID="test-seller",
        )
        with patch.dict(os.environ, config):
            wx = self.order("微信支付")
            ali = self.order("支付宝")
            order = {
                "appid": "test-wx",
                "mchid": "test-merchant",
                "trade_state": "SUCCESS",
                "out_trade_no": wx,
                "transaction_id": "wx-100",
                "amount": {"total": 1220, "currency": "CNY"},
                "success_time": self.now.isoformat(),
            }
            nonce = "012345678912"
            associated = "transaction"
            cipher = AESGCM(aes).encrypt(
                nonce.encode(), json.dumps(order).encode(), associated.encode()
            )
            body = json.dumps(
                {
                    "event_type": "TRANSACTION.SUCCESS",
                    "id": "wx-event",
                    "resource": {
                        "algorithm": "AEAD_AES_256_GCM",
                        "nonce": nonce,
                        "associated_data": associated,
                        "ciphertext": base64.b64encode(cipher).decode(),
                    },
                }
            ).encode()
            stamp = str(int(self.now.timestamp()))
            headers = {
                "Wechatpay-Serial": "test-key",
                "Wechatpay-Timestamp": stamp,
                "Wechatpay-Nonce": "other-nonce",
                "Wechatpay-Signature": sign(
                    (stamp + "\nother-nonce\n").encode() + body + b"\n"
                ),
            }
            with self.assertRaises(PermissionError):
                channels.receive(self.store, "wechat", headers, body + b" ")
            with ThreadPoolExecutor(2) as pool:
                list(
                    pool.map(
                        lambda _: channels.receive(self.store, "wechat", headers, body),
                        range(2),
                    )
                )
            self.assertEqual(len(self.data()["channelReceipts"]), 1)
            self.assertEqual(
                self.data()["channelReceipts"][0]["verification"], "渠道签名通知"
            )
            remaining = next(
                b["balance"] for b in self.data()["bills"] if b["id"] == self.bill["id"]
            )
            self.command("pay", billId=self.bill["id"], amount=remaining)
            form = dict(
                app_id="test-ali",
                seller_id="test-seller",
                trade_status="TRADE_SUCCESS",
                total_amount="12.20",
                gmt_payment="2026-11-24 13:55:00",
                out_trade_no=ali,
                trade_no="ali-200",
                notify_id="notify-A",
                charset="utf-8",
            )
            form["sign"] = sign(
                "&".join(k + "=" + form[k] for k in sorted(form)).encode()
            )
            form["sign_type"] = "RSA2"
            with self.assertRaises(PermissionError):
                channels.receive(
                    self.store,
                    "alipay",
                    {},
                    urlencode({**form, "total_amount": "13.20"}).encode(),
                )
            channels.receive(self.store, "alipay", {}, urlencode(form).encode())
            before = self.store.version(self.user)["revision"]
            channels.receive(self.store, "alipay", {}, urlencode(form).encode())
            self.assertEqual(self.store.version(self.user)["revision"], before)
            self.assertEqual(self.data()["channelReceipts"][0]["depositAmount"], 12.2)
            self.assertEqual(self.data()["depositEntries"][0]["amount"], 12.2)
            self.assertEqual(
                self.store.snapshot(self.user)["audit"][0]["actorId"], "channel-alipay"
            )


class HistoricalCharges(unittest.TestCase):
    def test_transfers_approved_level_and_leave_frozen_per_day(self):
        state = {
            "bills": [],
            "payments": [],
            "deposits": [],
            "residents": [
                dict(
                    id="r",
                    name="测试",
                    admittedAt="2026-11-01",
                    dischargedAt="2026-11-06",
                    status="已退住",
                    bedId="",
                    level="半失能",
                )
            ],
            "beds": [
                dict(id="one", label="101-1", dailyRate=99),
                dict(id="two", label="201-1", dailyRate=180),
            ],
            "bedMoves": [
                dict(
                    residentId="r",
                    bedId="one",
                    date="2026-11-01",
                    bedDailyRate=60,
                    initialCareLevel="自理",
                ),
                dict(residentId="r", bedId="two", date="2026-11-04", bedDailyRate=120),
                dict(residentId="r", bedId="", date="2026-11-06"),
            ],
            "plans": [
                dict(
                    residentId="r",
                    status="已派发",
                    reviewedAt="2026-11-03",
                    careLevel="半失能",
                    previousCareLevel="自理",
                )
            ],
            "leaves": [
                dict(residentId="r", startDate="2026-11-03", endDate="2026-11-04")
            ],
        }
        with self.assertRaises(ValueError):
            generate_bill(
                state, dict(month="2026-11", residentId="r", leaveDays=1), "2026-11-20"
            )
        generate_bill(state, dict(month="2026-11", residentId="r"), "2026-11-20")
        bill = state["bills"][0]
        self.assertEqual([p["days"] for p in bill["segments"]], [2, 1, 3])
        self.assertEqual(
            (bill["bedTotal"], bill["careTotal"], bill["amount"]), (540, 130, 670)
        )
