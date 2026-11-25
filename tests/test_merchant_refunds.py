"""Exercise original-channel refunds against independently signed local merchant responses."""
from base64 import b64encode
from contextlib import closing
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl

from platform_core.operations import channels, checkout, merchant_refunds as gateway
from platform_core.store import Store, TIMEZONE
from test_checkout import LocalMerchants, rsa


@unittest.skipUnless(rsa and checkout.find_spec("qrcode"), "optional merchant packages")
class MerchantRefundTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.now = datetime(2026, 11, 24, 15, tzinfo=TIMEZONE)
        self.keys = LocalMerchants(root, self.now)
        self.enterContext(patch.dict(os.environ, self.keys.config))
        self.store = Store(root/"data", now=lambda: self.now, initial_owner_password="local-refunds-fixture")
        self.token, _ = self.store.login("owner", "local-refunds-fixture")
        self.mock = self.enterContext(patch.object(checkout, "send", self.send))
        self.reqs = []
        self.response = "PROCESSING"
        self.overrides = {}
        self.tamper = False

    def data(self):
        return self.store.snapshot(self.token)["data"]

    def execute(self, action, p):
        return self.store.execute(action, p, self.store.version(self.token)["revision"], self.token)

    def prepare(self, channel):
        b = next(b for b in self.data()["bills"] if b["balance"] > 20)
        self.rid = b["residentId"]
        self.execute("ops.paymentOrder", dict(billId=b["id"], channel=channel, amount=12.20))
        self.order = self.data()["paymentOrders"][0]["id"]
        self.tx = "GatewayTrade001"
        receipt = channels.record_verified(self.store, "local", dict(channel=channel,
            transactionId=self.tx, merchantOrder=self.order, amount="12.20",
            paidDate="2026-11-24", source="test"), self.now, "渠道签名通知")
        self.execute("ops.requestRefund", dict(mode="channel", residentId=self.rid, receiptId=receipt,
            requestId="cashier-request", amount=3.21, reason="原单部分退款"))
        self.refund = self.data()["refunds"][0]["id"]

    def act(self, operation, token=None, confirmed=True):
        return gateway.perform(self.store, token or self.token,
            {"refundId":self.refund, "confirmed":confirmed, "operation":operation})

    def wxdata(self):
        return {"refund_id":"500000001", "out_trade_no":self.order, "out_refund_no":self.refund,
                "transaction_id":self.tx, "amount":{"total":1220, "refund":321}, **self.overrides}

    def signed_wx(self, raw):
        now = str(int(self.now.timestamp()))
        return {"Wechatpay-Timestamp":now, "Wechatpay-Nonce":"nonce", "Wechatpay-Serial":"PUB_KEY_ID_61",
                "Wechatpay-Signature":self.keys.signed((now+"\nnonce\n").encode()+raw+b"\n")}

    def send(self, host, path, body, headers, **options):
        if host == "api.mch.weixin.qq.com":
            method = options.get("method", "POST")
            values = dict(re.findall(r'(\w+)="([^"]+)"', headers["Authorization"]))
            self.keys.verify(values["signature"], f"{method}\n{path}\n{values['timestamp']}\n{values['nonce_str']}\n".encode()+body+b"\n")
            self.assertEqual(path, gateway.WX_PATH + ("/"+self.refund if method == "GET" else ""))
            if method == "POST":
                params = json.loads(body)
                self.assertEqual(params["out_refund_no"], self.refund)
                self.assertEqual(params["transaction_id"], self.tx)
                self.assertEqual(params["amount"], {"total":1220,"refund":321,"currency":"CNY"})
                self.assertEqual(params["notify_url"], "https://care.example.org"+gateway.WX_NOTIFY)
            self.reqs.append((method,self.refund))
            if self.response == "TIMEOUT":
                raise ValueError("连接超时")
            data = dict(status=self.response, **self.wxdata())
            if self.response == "SUCCESS":
                data["success_time"] = self.now.isoformat()
            raw = checkout.compact(data).encode()
            return self.signed_wx(raw), raw + (b" " if self.tamper else b"")
        self.assertEqual(host, "openapi.alipay.com")
        params = dict(parse_qsl(body.decode()))
        signature = params.pop("sign")
        self.keys.verify(signature, "&".join(k+"="+params[k] for k in sorted(params)).encode())
        biz = json.loads(params["biz_content"])
        self.assertEqual((biz["trade_no"],biz["out_request_no"]),(self.tx,self.refund))
        method = params["method"]
        self.reqs.append((method, biz["out_request_no"]))
        if self.response == "TIMEOUT":
            raise ValueError("连接超时")
        data = dict(code="10000", trade_no=self.tx, out_trade_no=self.order)
        if method == "alipay.trade.refund":
            self.assertEqual(biz["refund_amount"], "3.21")
            data.update(fund_change="Y", refund_fee="12.20")
        else:
            self.assertEqual(method, "alipay.trade.fastpay.refund.query")
            self.assertNotIn("refund_amount", biz)
            if self.response == "SUCCESS":
                data.update(refund_status="REFUND_SUCCESS", out_request_no=self.refund, refund_amount="3.21",
                            total_amount="12.20", gmt_refund_pay="2026-11-24 15:00:00")
        data.update(self.overrides)
        return {}, checkout.compact({method.replace(".","_")+"_response":data,
            "sign":self.keys.signed(checkout.compact(data).encode()+(b" " if self.tamper else b""))}).encode()

    def callback(self, status, **extra):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        info = dict(self.wxdata(), refund_status=status, mchid="12345", **extra)
        if status == "SUCCESS":
            info["success_time"] = self.now.isoformat()
        aes = AESGCM(channels.material("WXPAY_V3_KEY_FILE"))
        iv = "123456789012"
        encrypted = aes.encrypt(iv.encode(),checkout.compact(info).encode(),b"refund")
        event = {"event_type":"REFUND."+status, "id":"event-123", "resource":{"algorithm":"AEAD_AES_256_GCM",
                 "nonce":iv,"associated_data":"refund","ciphertext":b64encode(encrypted).decode()}}
        raw=checkout.compact(event).encode()
        return gateway.receive_wechat(self.store,self.signed_wx(raw),raw+(b" " if self.tamper else b""))

    def booked(self):
        return [r for r in self.data()["payments"] if r.get("refundOf")]

    def test_wechat_requires_consent_and_closes_once_on_verified_callback(self):
        self.prepare("微信支付")
        with self.assertRaises(ValueError):
            self.act("submit", confirmed=False)
        with self.assertRaises(ValueError):
            self.act("query")
        with self.assertRaises(ValueError):
            self.callback("SUCCESS")
        self.execute("access.create", dict(kind="staff",role="自定义",username="care-nofinance",
                     password="read-only-refund",displayName="测试员工",permissions=["care"]))
        staff, _ = self.store.login("care-nofinance", "read-only-refund")
        with self.assertRaises(PermissionError):
            self.act("submit",staff)
        self.assertFalse(self.reqs)
        self.response = "SUCCESS"
        self.assertEqual(self.act("submit")["status"], "渠道处理中")
        self.act("submit")
        self.assertEqual(len(self.reqs), 1)
        self.assertEqual(self.booked(), [])
        self.tamper = True
        with self.assertRaises(PermissionError):
            self.callback("SUCCESS")
        self.tamper = False
        self.overrides = {"transaction_id":"other"}
        with self.assertRaises(ValueError):
            self.callback("SUCCESS")
        self.overrides = {}
        self.callback("ABNORMAL")
        self.assertIn("异常", self.data()["refunds"][0]["channelMessage"])
        self.assertEqual(self.booked(), [])
        self.callback("SUCCESS")
        revision = self.store.version(self.token)["revision"]
        self.callback("SUCCESS")
        self.act("query")
        self.assertEqual(self.store.version(self.token)["revision"], revision)
        self.assertEqual([p["amount"] for p in self.booked()], [-3.21])

    def test_wechat_timeout_then_same_id_retry_and_signed_closed(self):
        self.prepare("微信支付")
        self.response = "TIMEOUT"
        with self.assertRaisesRegex(ValueError, "超时"):
            self.act("submit")
        self.assertEqual(self.data()["refunds"][0]["status"], "渠道处理中")
        self.now += timedelta(minutes=1)
        self.response = "PROCESSING"
        self.act("submit")
        self.assertEqual(self.reqs, [("POST",self.refund),("POST",self.refund)])
        self.tamper = True
        with self.assertRaises(PermissionError):
            self.act("query")
        self.tamper = False
        self.response = "CLOSED"
        self.assertEqual(self.act("query")["status"], "已取消")
        self.assertEqual(self.reqs[-1],("GET",self.refund))
        self.assertEqual(self.booked(), [])

    def test_callback_may_arrive_while_submission_is_waiting(self):
        self.prepare("微信支付")
        def arrive_first(*args, **kwargs):
            # Independent DB connection, as used by the notification HTTP handler.
            self.callback("SUCCESS")
            return self.send(*args, **kwargs)
        with patch.object(checkout, "send", arrive_first):
            self.assertEqual(self.act("submit")["status"], "已退款")
        self.assertEqual(len(self.booked()), 1)

    def test_alipay_uses_per_request_query_recovers_after_restart(self):
        self.prepare("支付宝")
        self.act("submit")
        self.act("query")
        self.assertEqual(self.booked(), [])
        self.response = "SUCCESS"
        for key, value in (("out_request_no","other"),("refund_amount","4.21"),("trade_no","other")):
            self.overrides = {key:value}
            with self.assertRaises(ValueError):
                self.act("query")
        self.overrides = {}
        self.tamper = True
        with self.assertRaises(PermissionError):
            self.act("query")
        self.tamper = False
        self.assertEqual(self.booked(), [])
        gateway.reconcile_due(self.store,Event())
        self.assertEqual(self.booked(), [])
        self.now += timedelta(days=1)
        reopened = Store(self.store.path, now=lambda:self.now)
        gateway.reconcile_due(reopened,Event())
        self.assertEqual([p["amount"] for p in self.booked()], [-3.21])
        self.assertEqual(self.booked()[0]["date"], "2026-11-24")
        count = len(self.reqs)
        gateway.reconcile_due(reopened,Event())
        self.assertEqual(len(self.reqs),count)
        with closing(reopened.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM merchant_refund_checks").fetchone()[0],0)
