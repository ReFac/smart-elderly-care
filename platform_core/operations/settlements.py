"""Cash vouchers, independently confirmed channel receipts and overdue follow-up."""

from decimal import Decimal
import re

from . import payment_terms
from .billing import apply_deposit, get_account, post_receipt
from .records import currency_amount, lookup, new_id, parse_day, text_field

CHANNELS = ("微信支付", "支付宝")
EXPENSES = ("照护耗材", "餐饮", "人力", "设施", "其他")


def paid_day(value, today):
    day = parse_day(value)
    if day > parse_day(today):
        raise ValueError("到账或支出日期不能在未来")
    return day.isoformat()


def create_order(state, p, today):
    bill = lookup(state, "bills", p.get("billId"), "账单")
    if p.get("channel") not in CHANNELS:
        raise ValueError("请选择有效支付渠道")
    amount = currency_amount(p.get("amount"), "订单金额", zero=False)
    previous_balance = bill["balance"]
    account = next(
        (r for r in state["deposits"] if r["residentId"] == bill["residentId"]), None
    )
    if account and account["amount"] > 0:
        apply_deposit(state, account, today)
        if bill["balance"] != previous_balance:
            return (
                f"已优先冲抵预缴金，本单剩余待缴 ¥{bill['balance']:.2f}，请按新余额核对"
            )
    if not bill["balance"] or (
        amount > Decimal(str(bill["balance"])) and p.get("carrySurplus") is not True
    ):
        raise ValueError("订单金额超过待缴余额")
    orders = state.setdefault("paymentOrders", [])
    prior = next(
        (
            r
            for r in orders
            if r["billId"] == bill["id"]
            and r["channel"] == p["channel"]
            and r["status"] == "待支付"
            and Decimal(str(r["amount"])) == amount
            and (
                amount <= Decimal(str(bill["balance"]))
                or r.get("balanceAtIssue") == bill["balance"]
            )
        ),
        None,
    )
    if prior:
        return f"沿用待支付商户订单 {prior['id']}"
    number = new_id("NH")
    orders.insert(
        0,
        dict(
            id=number,
            billId=bill["id"],
            residentId=bill["residentId"],
            amount=float(amount),
            channel=p["channel"],
            balanceAtIssue=bill["balance"],
            feeRateBps=payment_terms.rate_for(state, p["channel"]),
            date=today,
            status="待支付",
        ),
    )
    return f"为账单生成{p['channel']}商户订单 {number}"


def admission_order(state, p, today):
    from . import checkout, terminal

    if set(p) != {"residentId", "channel", "amount", "collection", "requestId"}:
        raise ValueError("请选择长辈档案、渠道和定额")
    person = lookup(state, "residents", p["residentId"], "长辈档案")
    if person["status"] != "未入住" and not (
        person.get("stayType") == "trial" and person["status"] in ("在住", "试住到期待确认")
    ):
        raise ValueError("请选择待办理正式入住的档案")
    channel, collection = p["channel"], p["collection"]
    terminal_id = ""
    if collection == "terminal" and channel in terminal.CHANNELS:
        terminal_id = terminal.configured_id()
        if not terminal_id:
            raise ValueError("机构尚未配置收银终端")
    elif collection != "qr" or channel not in checkout.enabled_channels():
        raise ValueError("机构尚未开通所选收款渠道")
    amount = currency_amount(p["amount"], "商户定额", zero=False)
    if not isinstance(p["requestId"], str) or not re.fullmatch(r"[a-f0-9]{32}", p["requestId"]):
        raise ValueError("收款请求号无效")
    orders = state.setdefault("paymentOrders", [])
    for order in orders:
        if order.get("requestId") == p["requestId"]:
            if not (order["residentId"] == person["id"] and order["amount"] == float(amount)
                    and order["channel"] == channel and order.get("collection") == collection):
                raise ValueError("同一请求的收款信息发生变化")
            return "沿用原入住收款订单 " + order["id"]
    number = new_id("NH")
    orders.insert(0, dict(id=number, residentId=person["id"], billId="", purpose="admission",
                          channel=channel, collection=collection, terminalId=terminal_id,
                          requestId=p["requestId"], amount=float(amount), status="待支付", date=today,
                          feeRateBps=payment_terms.rate_for(state, channel)))
    return f"为入住预收生成{channel}定额订单 {number}"


def settle(state, p, today, *, verification):
    channel = p.get("channel")
    if channel not in CHANNELS and not (channel == "银联刷卡" and verification == "终端签名通知"):
        raise ValueError("请选择有效支付渠道")
    txn = text_field(p, "transactionId", "渠道交易号", 100)
    amount = currency_amount(p.get("amount"), "实收金额", zero=False)
    day = paid_day(p.get("paidDate"), today)
    order_id = text_field(p, "merchantOrder", "商户订单号", 100)
    order = next(
        (r for r in state.get("paymentOrders", []) if r["id"] == order_id), None
    )
    if order:
        if (order.get("collection") == "terminal") != (verification == "终端签名通知"):
            raise ValueError("收款方式不匹配")
        if order.get("collection") == "terminal" and order["terminalId"] != p.get("terminalId"):
            raise ValueError("收银终端与订单不匹配")
        if order.get("purpose") == "admission" and verification not in ("渠道签名通知", "终端签名通知"):
            raise ValueError("入住在线收款须由签名回执确认")
        if (
            order["channel"] != channel
            or Decimal(str(order["amount"])) != amount
            or (p.get("billId") and order["billId"] != p["billId"])
        ):
            raise ValueError("订单的渠道、金额或账单不匹配")
        bill_id = order["billId"]
    else:
        if verification in ("渠道签名通知", "终端签名通知"):
            raise ValueError("找不到已登记的商户订单")
        bill_id = p.get("billId")
    advance = bool(order and order.get("purpose") == "admission")
    bill = None if advance else lookup(state, "bills", bill_id, "账单")
    resident_id = order["residentId"] if advance else bill["residentId"]
    receipts = state.setdefault("channelReceipts", [])
    for prior in receipts:
        if prior["channel"] == channel and (
            prior["transactionId"] == txn or prior["merchantOrder"] == order_id
        ):
            if (
                prior["billId"],
                prior["transactionId"],
                prior["merchantOrder"],
                Decimal(str(prior["amount"])),
                prior["paidDate"],
            ) == (bill_id, txn, order_id, amount, day):
                return prior, False
            raise ValueError("渠道流水或商户订单已关联另一笔记录")
    if any(
        r.get("channel") == channel
        and not r.get("originBillId")
        and (r.get("transactionId") == txn or r.get("merchantOrder") == order_id)
        for r in state["depositEntries"]
    ):
        raise ValueError("此笔交易已单独登记为预缴金，请核对原始凭证")
    if order and order["status"] != "待支付":
        raise ValueError("商户订单已处理")
    receipt = dict(
        id=new_id("channel"),
        channel=channel,
        transactionId=txn,
        merchantOrder=order_id,
        billId=bill_id,
        residentId=resident_id,
        amount=float(amount),
        paidDate=day,
        date=today,
        verification=verification,
        source=text_field(p, "source", "对账依据", 160),
    )
    rate = (order or {}).get("feeRateBps", payment_terms.rate_for(state, channel))
    origin = dict(receiptId=receipt["id"], transactionId=txn, merchantOrder=order_id)
    if verification == "线下登记核对" and p.get("paymentRef"):
        origin["paymentRef"] = p["paymentRef"]
    allocation = post_receipt(
        state,
        resident_id=resident_id,
        bill=bill,
        amount=amount,
        method="线下登记" if verification == "线下登记核对" else channel,
        channel=channel,
        day=day,
        rate=rate,
        origin=origin,
    )
    receipt.update(allocation)
    receipts.insert(0, receipt)
    if order:
        order.update(status="已到账", receiptId=receipt["id"])
    return receipt, True


def import_receipt(state, p, today):
    if set(p) - {
        "channel",
        "transactionId",
        "merchantOrder",
        "billId",
        "amount",
        "paidDate",
        "source",
    }:
        raise ValueError("对账凭证含有不支持的字段")
    receipt, added = settle(state, p, today, verification="财务人工核对")
    return (
        "登记" if added else "已核对同一笔"
    ) + f"{receipt['channel']}实收 ¥{receipt['amount']:.2f}"


def expense(state, p, today):
    if p.get("category") not in EXPENSES:
        raise ValueError("请选择支出分类")
    ref = text_field(p, "voucher", "支出凭证号", 100)
    row = dict(
        category=p["category"],
        voucher=ref,
        amount=float(currency_amount(p.get("amount"), "支出金额", zero=False)),
        date=paid_day(p.get("date"), today),
        payee=text_field(p, "payee", "收款对象", 80),
        note=text_field(p, "note", "支出事由"),
    )
    entries = state.setdefault("expenses", [])
    if any(r["voucher"] == ref for r in entries):
        raise ValueError("该支出凭证号已登记")
    entries.insert(0, dict(id=new_id("expense"), **row))
    return f"登记{row['category']}支出 ¥{row['amount']:.2f}，凭证 {ref}"


def remind(state, p, today):
    bill = lookup(state, "bills", p.get("billId"), "账单")
    if not bill["balance"] or not bill.get("endDate") or bill["endDate"] >= today:
        raise ValueError("请选择服务期已结束且仍然欠费的账单")
    if p.get("channel") not in ("电话", "当面", "机构消息"):
        raise ValueError("请选择实际跟进方式")
    note = text_field(p, "note", "跟进结果")
    apply_deposit(state, get_account(state, bill["residentId"]), today)
    if not bill["balance"]:
        return "预缴金已冲清本单，无需催缴"
    bill.setdefault("reminders", []).insert(
        0,
        dict(
            id=new_id("follow"),
            channel=p["channel"],
            date=today,
            balance=bill["balance"],
            note=note,
        ),
    )
    return f"登记 {bill['month']} 未结账单的催缴跟进"
