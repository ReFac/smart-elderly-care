"""Exercise merchant-signed requests and independent gateway-signed responses offline."""

from base64 import b64decode, b64encode
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import parse_qsl
from unittest.mock import patch

from platform_core.operations import checkout
from platform_core.store import Store, TIMEZONE

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:
    rsa = None


class LocalMerchants:
    def __init__(self, root, now):
        self.now = now
        self.calls = []
        self.tamper = False
        self.priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.platform = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub, key, secret = [
            root / k for k in ("platform.pem", "merchant.pem", "v3.bin")
        ]
        pub.write_bytes(
            self.platform.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        key.write_bytes(
            self.priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        secret.write_bytes(os.urandom(16).hex().encode())
        self.config = dict(
            NH_PAYMENT_PUBLIC_ORIGIN="https://care.example.org",
            NH_WXPAY_APP_ID="wx-test",
            NH_WXPAY_MERCHANT_ID="12345",
            NH_WXPAY_PUBLIC_KEY_ID="PUB_KEY_ID_61",
            NH_WXPAY_CERT_SERIAL="0123AB",
            NH_WXPAY_PRIVATE_KEY_FILE=str(key),
            NH_WXPAY_PUBLIC_KEY_FILE=str(pub),
            NH_WXPAY_V3_KEY_FILE=str(secret),
            NH_ALIPAY_APP_ID="ali-test",
            NH_ALIPAY_SELLER_ID="2088",
            NH_ALIPAY_PUBLIC_KEY_FILE=str(pub),
            NH_ALIPAY_PRIVATE_KEY_FILE=str(key),
        )

    def signed(self, value):
        return b64encode(
            self.platform.sign(value, padding.PKCS1v15(), hashes.SHA256())
        ).decode()

    def verify(self, sig, data):
        self.priv.public_key().verify(
            b64decode(sig, validate=True), data, padding.PKCS1v15(), hashes.SHA256()
        )

    def send(self, host, path, body, headers):
        self.calls.append(host)
        if host == "api.mch.weixin.qq.com":
            if path != "/v3/pay/transactions/native":
                raise AssertionError(path)
            params = dict(re.findall(r'(\w+)="([^"]+)"', headers["Authorization"]))
            self.verify(
                params["signature"],
                f"POST\n{path}\n{params['timestamp']}\n{params['nonce_str']}\n".encode()
                + body
                + b"\n",
            )
            request = json.loads(body)
            if (
                request["amount"] != {"total": 1220, "currency": "CNY"}
                or params["serial_no"] != "0123AB"
                or request["notify_url"]
                != "https://care.example.org/api/payments/notify/wechat"
            ):
                raise AssertionError("incorrect native payload")
            raw = b'{"code_url":"weixin://wxpay/bizpayurl?pr=LOCAL-TEST"}'
            stamp = str(int(self.now.timestamp()))
            resp = {
                "Wechatpay-Serial": "PUB_KEY_ID_61",
                "Wechatpay-Timestamp": stamp,
                "Wechatpay-Nonce": "merchant-test",
                "Wechatpay-Signature": self.signed(
                    (stamp + "\nmerchant-test\n").encode() + raw + b"\n"
                ),
            }
            return resp, raw + b" " if self.tamper else raw
        if host != "openapi.alipay.com" or path != "/gateway.do?charset=utf-8":
            raise AssertionError(host + path)
        params = dict(parse_qsl(body.decode()))
        signature = params.pop("sign")
        self.verify(
            signature, "&".join(k + "=" + params[k] for k in sorted(params)).encode()
        )
        biz = json.loads(params["biz_content"])
        if (
            params["method"] != "alipay.trade.precreate"
            or biz["total_amount"] != "12.20"
            or params["notify_url"]
            != "https://care.example.org/api/payments/notify/alipay"
        ):
            raise AssertionError("incorrect precreate payload")
        result = json.dumps(
            {
                "code": "10000",
                "msg": "Success",
                "out_trade_no": biz["out_trade_no"],
                "qr_code": "https://qr.alipay.com/LOCAL-TEST",
            },
            ensure_ascii=False,
        )
        data = (
            '{"alipay_trade_precreate_response":'
            + result
            + ',"sign":"'
            + self.signed(result.encode())
            + '"}'
        )
        return {}, (
            data.replace("Success", "Tampered") if self.tamper else data
        ).encode()


@unittest.skipUnless(rsa, "optional cryptography package")
class MerchantCheckout(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.now = datetime(2026, 11, 24, 15, 0, tzinfo=TIMEZONE)
        self.mock = LocalMerchants(root, self.now)
        self.enterContext(
            patch.dict(
                os.environ,
                {**self.mock.config, "NH_OWNER_PASSWORD": "merchant-checkout-test"},
            )
        )
        self.enterContext(patch.object(checkout, "send", self.mock.send))
        self.store = Store(root / "workspace", now=lambda: self.now)
        self.user, _ = self.store.login("owner", "merchant-checkout-test")
        self.bill = next(b for b in self.data()["bills"] if b["balance"] > 20)

    def data(self):
        return self.store.snapshot(self.user)["data"]

    def command(self, name, payload):
        self.store.execute(
            name, payload, self.store.version(self.user)["revision"], self.user
        )

    def order(self, channel):
        self.command(
            "ops.paymentOrder",
            dict(channel=channel, billId=self.bill["id"], amount="12.20"),
        )
        return self.data()["paymentOrders"][0]

    @unittest.skipUnless(checkout.find_spec("qrcode"), "optional qrcode payment package")
    def test_admission_can_issue_fixed_qr_before_a_bill_or_bed_exists(self):
        self.command("care.register", {"name":"扫码入住演练"})
        rid = self.data()["residents"][-1]["id"]
        for index, channel in enumerate(checkout.CONFIG):
            self.command("ops.admissionOrder", dict(residentId=rid, channel=channel, amount="12.20",
                                                    collection="qr", requestId=str(index)*32))
            order = self.data()["paymentOrders"][0]
            code = self.store.payment_checkout(self.user, order["id"])
            self.assertIn("LOCAL-TEST", code["checkoutUrl"])
            self.assertEqual((code["amount"], code["channel"]), (12.20, channel))
            self.assertTrue(code["matrix"])
            self.assertEqual(order["billId"], "")
        self.assertFalse([b for b in self.data()["bills"] if b["residentId"] == rid])

    def test_signed_requests_and_tampered_responses(self):
        for channel in checkout.CONFIG:
            order = self.order(channel)
            self.mock.tamper = False
            self.assertIn("LOCAL-TEST", checkout.precreate(order, self.now))
            self.mock.tamper = True
            with self.assertRaises(PermissionError):
                checkout.precreate(order, self.now)
        self.assertEqual(self.data()["channelReceipts"], [])

    @unittest.skipUnless(
        checkout.find_spec("qrcode"), "optional qrcode payment package"
    )
    def test_cashier_access_qr_cache_audit_and_paid_state(self):
        self.assertEqual(
            set(self.store.payment_channels(self.user)["channels"]),
            set(checkout.CONFIG),
        )
        self.command(
            "access.create",
            dict(
                kind="staff",
                username="care-q",
                role="护工",
                displayName="护理",
                password="test-patient-checkout",
                permissions=["care"],
            ),
        )
        staff, _ = self.store.login("care-q", "test-patient-checkout")
        order = self.order("支付宝")
        with self.assertRaises(PermissionError):
            self.store.payment_checkout(staff, order["id"])
        with self.assertRaises(PermissionError):
            self.store.payment_channels(staff)
        self.assertEqual(self.mock.calls, [])
        self.assertNotIn(
            "checkoutUrl", self.store.payment_order_status(self.user, order["id"])
        )
        a = self.store.payment_checkout(self.user, order["id"])
        current = self.store.payment_order_status(self.user, order["id"])
        self.assertEqual(
            (current["checkoutUrl"], current["channel"], current["expiresAt"]),
            (a["checkoutUrl"], "支付宝", a["expiresAt"]),
        )
        self.assertEqual(self.store.payment_checkout(self.user, order["id"]), a)
        self.assertEqual(len(self.mock.calls), 1)
        self.assertTrue(all(len(row) == len(a["matrix"]) for row in a["matrix"]))
        self.assertTrue(any("1" in row for row in a["matrix"]))
        self.assertIn("收款码", self.store.snapshot(self.user)["audit"][0]["summary"])
        self.command(
            "ops.importReceipt",
            dict(
                channel="支付宝",
                billId=self.bill["id"],
                merchantOrder=order["id"],
                transactionId="M1",
                paidDate="2026-11-24",
                source="商户台账",
                amount=12.20,
            ),
        )
        self.assertEqual(
            self.store.payment_order_status(self.user, order["id"])["status"], "已到账"
        )
        self.assertNotIn(
            "checkoutUrl", self.store.payment_order_status(self.user, order["id"])
        )
        with self.assertRaises(ValueError):
            self.store.payment_checkout(self.user, order["id"])


if __name__ == "__main__":
    unittest.main()
