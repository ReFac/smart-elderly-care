"""Merchant refund submission, independent signed reconciliation and durable polling."""
from contextlib import closing
from datetime import datetime
import json
import logging
import re
from zoneinfo import ZoneInfo

from .. import access, activity, campus_access, history
from . import checkout, channels, refunds
from .records import currency_amount, lookup

WX_PATH = "/v3/refund/domestic/refunds"
WX_NOTIFY = "/api/payments/refunds/notify/wechat"
EVENTS = {"REFUND.SUCCESS", "REFUND.CLOSED", "REFUND.ABNORMAL"}
SYSTEM = dict(id="channel-refund", username="channel-refund", displayName="商户退款核对")
UNCONFIRMED = "尚未取得该笔退款的最终结果，将继续核对。"
QUEUE = """CREATE TABLE IF NOT EXISTS merchant_refund_checks (
    id TEXT PRIMARY KEY, next_at INTEGER NOT NULL, attempts INTEGER NOT NULL)"""
LOG = logging.getLogger(__name__)


def money(value):
    return refunds.cents(currency_amount(value, "渠道金额", zero=False))


def verify_origin(state, row):
    order = lookup(state, "paymentOrders", row["merchantOrder"], "已核实商户订单")
    receipt = lookup(state, "channelReceipts", row["receiptId"], "原签名收款凭证")
    if (row["mode"] != "channel" or order["status"] != "已到账" or order.get("collection") == "terminal"
            or order.get("receiptId") != receipt["id"] or receipt["verification"] != "渠道签名通知"
            or receipt["transactionId"] != row["transactionId"] or receipt["merchantOrder"] != order["id"]
            or any(record["channel"] != row["channel"] or record["residentId"] != row["residentId"]
                   or money(record["amount"]) != money(row["grossAmount"]) for record in (order, receipt))):
        raise ValueError("此申请缺少与原始渠道交易相符的已验签到账凭证")


def match_wechat(row, data, status_key):
    amount = data["amount"]
    if (data["out_trade_no"] != row["merchantOrder"] or data["transaction_id"] != row["transactionId"]
            or data["out_refund_no"] != row["id"] or not isinstance(data["refund_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", data["refund_id"])
            or any(type(amount.get(key)) is not int for key in ("total", "refund"))
            or amount.get("currency", "CNY") != "CNY" or amount["total"] != money(row["grossAmount"])
            or amount["refund"] != money(row["amount"])):
        raise ValueError("微信退款应答与原订单、退款申请或金额不一致")
    status = data[status_key]
    if status not in {"SUCCESS", "PROCESSING", "ABNORMAL", "CLOSED"}:
        raise ValueError("微信退款状态无法确认")
    return status, data["refund_id"], data.get("success_time")


def remote(row, operation, now):
    submit = operation == "submit"
    if row["channel"] == "微信支付":
        if submit:
            data = checkout.wechat_api(WX_PATH, now, {
                "transaction_id": row["transactionId"], "out_refund_no": row["id"],
                "notify_url": checkout.notify_origin() + WX_NOTIFY,
                "amount": {"refund": money(row["amount"]), "total": money(row["grossAmount"]), "currency": "CNY"},
            })
        else:
            data = checkout.wechat_api(WX_PATH + "/" + row["id"], now)
        outcome = match_wechat(row, data, "status")
        # WeChat's submission endpoint acknowledges acceptance. The query or callback settles it.
        return ("PROCESSING", "", None) if submit else outcome
    biz = {"trade_no": row["transactionId"], "out_request_no": row["id"]}
    if submit:
        biz["refund_amount"] = f"{row['amount']:.2f}"
    method = "alipay.trade.refund" if submit else "alipay.trade.fastpay.refund.query"
    data = checkout.alipay_api(method, biz, now)
    if data.get("code") != "10000" or (not submit and not data.get("refund_status")):
        return "PROCESSING", "", None
    if data.get("trade_no") != row["transactionId"] or data.get("out_trade_no") != row["merchantOrder"]:
        raise ValueError("支付宝退款应答与原交易不一致")
    # A submission's refund_fee can be cumulative. Require this request's signed query amount.
    if submit or data["refund_status"] != "REFUND_SUCCESS":
        return "PROCESSING", "", None
    if (data.get("out_request_no") != row["id"] or money(data.get("refund_amount")) != money(row["amount"])
            or (data.get("total_amount") is not None and money(data["total_amount"]) != money(row["grossAmount"]))):
        raise ValueError("支付宝逐笔退款查询的请求号或金额不匹配")
    return "SUCCESS", row["id"], data.get("gmt_refund_pay")


def load(db, refund_id):
    revision, raw = db.execute("SELECT revision,data FROM workspace WHERE id=1").fetchone()
    state = json.loads(raw)
    return revision, state, lookup(state, "refunds", refund_id, "退款申请")


def save(db, revision, state, row, actor, now, summary):
    history.watch(db, "ops.confirmRefund")
    db.execute("UPDATE workspace SET revision=?,data=? WHERE id=1", (revision + 1, checkout.compact(state)))
    activity.write(db, revision + 1, now.isoformat(timespec="seconds"), "ops.confirmRefund", summary,
                   actor, activity.for_person(state, row["residentId"]), {})


def status(row, message=""):
    return {"refundId": row["id"], "status": row["status"], "message": message or row["status"]}


def finish(store, refund_id, *, response=None, notification=None, actor=SYSTEM, channel=None):
    now = store.now()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        revision, state, row = load(db, refund_id)
        if row["mode"] != "channel" or not row.get("channelStartedAt") or (channel and row["channel"] != channel):
            raise ValueError("未找到员工已确认的对应渠道退款")
        if notification is not None:
            response = match_wechat(row, notification, "refund_status")
        outcome, reference, when = response
        if row["status"] not in refunds.PENDING:
            if outcome == "SUCCESS" and (row["status"] != "已退款" or row["reference"] != reference):
                raise ValueError("渠道结果与已登记的最终退款凭证冲突")
            if outcome == "CLOSED" and row["status"] != "已取消":
                raise ValueError("渠道关闭结果与已登记的凭证冲突")
            return status(row)
        if outcome == "PROCESSING":
            return status(row, UNCONFIRMED)
        if outcome == "ABNORMAL":
            message = "微信支付退款异常，请在原商户平台核对并处理。退款金额仍受保护。"
            if row.get("channelMessage") != message:
                row["channelMessage"] = message
                save(db, revision, state, row, actor, now, message)
            return status(row, message)
        day = now.date().isoformat()
        if when:
            actual = datetime.fromisoformat(when)
            zone = ZoneInfo("Asia/Shanghai")
            if actual.tzinfo is None:
                if row["channel"] == "微信支付":
                    raise ValueError("微信退款完成时间缺少时区")
                actual = actual.replace(tzinfo=zone)
            if actual > now:
                raise ValueError("退款完成时间在未来")
            day = actual.astimezone(zone).date().isoformat()
        message = refunds.resolve(state, row, actor, now.date().isoformat(), reference if outcome == "SUCCESS" else "",
                                  cancel=outcome == "CLOSED", refund_date=day)
        row["channelMessage"] = "渠道已确认退款成功" if outcome == "SUCCESS" else "渠道已确认退款关闭"
        save(db, revision, state, row, actor, now, row["channelMessage"] + "，退款单 " + row["id"])
        db.execute(QUEUE)
        db.execute("DELETE FROM merchant_refund_checks WHERE id=?", (refund_id,))
        return status(row, message)


def perform(store, token, body):
    if (not isinstance(body, dict) or set(body) != {"refundId", "operation", "confirmed"}
            or body["confirmed"] is not True or body["operation"] not in ("submit", "query")
            or not isinstance(body["refundId"], str) or not re.fullmatch(r"rf-[a-f0-9]{16}", body["refundId"])):
        raise ValueError("请本人核对并确认原路退款操作")
    return exchange(store, body["refundId"], body["operation"], token=token)


def exchange(store, refund_id, operation, *, token=None, scheduled=False):
    now = store.now()
    stamp = int(now.timestamp())
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = SYSTEM if scheduled else store.actor(db, token)
        if not scheduled:
            access.require(actor, "finance")
        revision, state, row = load(db, refund_id)
        if not scheduled:
            campus_access.require_resident(db, actor, row["residentId"], state)
        verify_origin(state, row)
        if row["status"] not in refunds.PENDING:
            return status(row)
        if row["channel"] not in checkout.enabled_channels():
            raise ValueError("尚未配置该商户的签名、验签与回调")
        if not row.get("channelStartedAt") and operation != "submit":
            raise ValueError("请先确认向商户发起退款")
        db.execute(QUEUE)
        marker = db.execute("SELECT next_at,attempts FROM merchant_refund_checks WHERE id=?", (refund_id,)).fetchone()
        if scheduled and marker and marker[0] > stamp:
            return status(row, UNCONFIRMED)
        if operation == "submit":
            if stamp - row.get("channelLastSubmit", 0) < 10:
                return status(row, "退款正在受理，请稍后查询原单。")
            row.setdefault("channelStartedAt", now.isoformat(timespec="seconds"))
            row.update(status="渠道处理中", channelLastSubmit=stamp, submittedBy=actor["id"])
            save(db, revision, state, row, actor, now, "员工确认提交原路退款，退款单 " + row["id"])
        attempts = min((marker[1] if marker else 0) + 1, 10)
        delay = min((60 if row["channel"] == "微信支付" else 15) * 2**(attempts-1), 3600)
        db.execute("INSERT OR REPLACE INTO merchant_refund_checks VALUES(?,?,?)", (refund_id, stamp + delay, attempts))
    # Submit intent is durable before the network call. Never hold a SQLite lock across the network.
    try:
        response = remote(row, operation, now)
        return finish(store, refund_id, response=response, actor=actor)
    except (KeyError, TypeError, AttributeError, UnicodeError) as error:
        raise ValueError("退款应答缺少有效字段，请使用同一退款申请查询") from error


def receive_wechat(store, headers, raw):
    try:
        event, data = channels.wechat_event(headers, raw, store.now(), EVENTS)
        if data["mchid"] != channels.setting("WXPAY_MERCHANT_ID") or event["event_type"] != "REFUND." + data["refund_status"]:
            raise PermissionError("退款通知商户或事件状态不匹配")
        return finish(store, data["out_refund_no"], notification=data, channel="微信支付")
    except (KeyError, TypeError, AttributeError, UnicodeError) as error:
        raise ValueError("退款通知缺少必要字段") from error


def reconcile_due(store, stopped):
    now = int(store.now().timestamp())
    with closing(store.connect()) as db, db:
        db.execute(QUEUE)
        due = db.execute("SELECT id FROM merchant_refund_checks WHERE next_at<=? ORDER BY next_at,id LIMIT 10", (now,)).fetchall()
    for (refund_id,) in due:
        if stopped.is_set():
            break
        try:
            exchange(store, refund_id, "query", scheduled=True)
        except (ValueError, PermissionError, OSError):
            LOG.warning("商户退款核对仍待确认 %s", refund_id)


def poll(store, stopped):
    from ..secure_storage import OPERATIONAL_ERRORS
    initialized = False
    while not stopped.is_set():
        try:
            if not initialized:
                with closing(store.connect()) as db, db:
                    db.execute(QUEUE)
                    db.execute("""INSERT OR IGNORE INTO merchant_refund_checks
                        SELECT json_extract(value,'$.id'),0,0 FROM workspace,json_each(data,'$.refunds')
                        WHERE json_extract(value,'$.status')='渠道处理中'""")
                initialized = True
            reconcile_due(store, stopped)
        except OPERATIONAL_ERRORS:
            LOG.warning("退款核对暂时无法读取资料库")
        stopped.wait(15)
