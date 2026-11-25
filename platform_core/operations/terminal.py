"""Vendor-neutral merchant terminal order lookup and signed CNY payment receipts."""

from contextlib import closing
from datetime import datetime
import hmac
import json
import os
import re
from zoneinfo import ZoneInfo

from .channels import material, record_verified
from .records import lookup

CHANNELS = ("微信支付", "支付宝", "银联刷卡")


def configured_id():
    name = os.environ.get("NH_TERMINAL_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
        return ""
    try:
        key = material("TERMINAL_KEY_FILE")
    except ValueError:
        return ""
    return name if len(key) >= 32 else ""


def handle(store, action, headers, raw):
    name = configured_id()
    if not name or headers.get("X-Terminal-Id") != name:
        raise PermissionError("未授权的收银终端")
    now = store.now()
    stamp = headers.get("X-Terminal-Time", "")
    if not re.fullmatch(r"[0-9]{1,12}", stamp) or abs(now.timestamp() - int(stamp)) > 300:
        raise PermissionError("终端时间无效")
    message = f"v1\n{name}\n{action}\n{stamp}\n".encode() + raw
    signature = headers.get("X-Terminal-Signature", "")
    if not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(
        hmac.digest(material("TERMINAL_KEY_FILE"), message, "sha256").hex(), signature
    ):
        raise PermissionError("收银终端签名无效")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("终端消息格式无效") from None
    fields = {"orderId"} if action == "lookup" else {"orderId","transactionId","paidAt","amountCents","currency","channel","status"}
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError("终端消息字段无效")
    with closing(store.connect()) as db:
        state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
        order = lookup(state, "paymentOrders", body["orderId"], "终端订单")
    if order.get("collection") != "terminal" or order.get("terminalId") != name:
        raise PermissionError("请使用该订单指定的收银终端")
    if action == "lookup":
        from decimal import Decimal
        return {"orderId": order["id"], "amountCents": int(Decimal(str(order["amount"]))*100),
                "currency": "CNY", "channel": order["channel"], "status": order["status"]}
    cents = body["amountCents"]
    if (type(cents) is not int or not 0 < cents <= 9999999900 or body["currency"] != "CNY"
            or body["status"] != "SUCCESS" or body["channel"] != order["channel"]):
        raise ValueError("仅受理订单渠道匹配的人民币到账回执")
    if not isinstance(body["paidAt"], str):
        raise ValueError("到账时间无效")
    paid = datetime.fromisoformat(body["paidAt"])
    if paid.tzinfo is None or paid > now:
        raise ValueError("实际支付时间须包含时区且不能在未来")
    data = dict(channel=body["channel"], transactionId=body["transactionId"], merchantOrder=order["id"],
                amount=f"{cents // 100}.{cents % 100:02d}", terminalId=name, source="终端 " + name,
                paidDate=paid.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat())
    receipt = record_verified(store, "terminal-" + name, data, now, "终端签名通知")
    return {"orderId": order["id"], "status": "已到账", "receiptId": receipt}
