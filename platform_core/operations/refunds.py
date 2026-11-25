"""Reverse a verified receipt, retaining the original tender and both accounting legs."""

from decimal import Decimal
from itertools import chain

from .records import currency_amount, lookup, new_id, parse_day, text_field
from .payment_terms import CASH_METHODS

PENDING = {"待核实", "渠道处理中"}
ACTIONS = {"ops.requestRefund", "ops.confirmRefund", "ops.cancelRefund"}


def cents(value):
    return int(Decimal(str(value)) * 100)


def yuan(value):
    return float(Decimal(value) / 100)


def held_for_bill(state, bill_id):
    return sum(
        part["cents"]
        for row in state.get("refunds", ())
        if row["status"] in PENDING
        for part in row["parts"]
        if part["billId"] == bill_id
    )


def payment_parts(state, rid, receipt):
    return [
        (bucket, row)
        for bucket in ("depositEntries", "payments")
        for row in state.get(bucket, ())
        if row["residentId"] == rid
        and (row.get("receiptId") or row["id"]) == receipt
        and row["amount"] > 0
        and (bucket == "depositEntries" or row["method"] in CASH_METHODS)
    ]


def _bill_limit(state, key):
    bill = lookup(state, "bills", key, "原账单")
    amount = cents(bill["paid"]) - held_for_bill(state, key)
    if bill.get("kind") == "security":
        amount -= cents(bill.get("refundedSecurity", 0))
        amount -= sum(
            cents(row["amount"])
            for row in state["payments"]
            if row.get("securityBillId") == key
        )
    return amount


def _candidates(state, origins, account, rid, receipt):
    for bucket, origin in origins:
        if bucket == "payments":
            yield (
                bucket,
                origin["id"],
                origin["billId"],
                cents(origin["amount"]),
                "",
                False,
            )
            continue
        sources = (account or {}).get("sources", {})
        missing = cents((account or {}).get("amount", 0)) - sum(
            cents(value) for value in sources.values()
        )
        tracked = bool(origin.get("trackedAdvance"))
        balance = cents(sources.get(receipt, 0)) if tracked else missing
        yield bucket, origin["id"], "", max(balance, 0), "", tracked
        for payment in state["payments"]:
            if payment["residentId"] != rid or payment["amount"] <= 0:
                continue
            applied = sum(
                cents(a["amount"])
                for a in payment.get("sourceAllocations", ())
                if a["receiptId"] == receipt
            )
            if applied:
                yield (
                    bucket,
                    origin["id"],
                    payment["billId"],
                    applied,
                    payment["id"],
                    False,
                )


def _reserve_advance(account, receipt, parts, direction):
    free = [p for p in parts if not p["billId"]]
    if not free:
        return
    account["amount"] = yuan(
        cents(account["amount"]) + direction * sum(p["cents"] for p in free)
    )
    tracked = sum(p["cents"] for p in free if p.get("tracked"))
    if tracked:
        sources = account.setdefault("sources", {})
        sources[receipt] = yuan(cents(sources.get(receipt, 0)) + direction * tracked)


def request(state, p, actor, today):
    rid = text_field(p, "residentId", "长辈档案编号", 100)
    receipt = text_field(p, "receiptId", "原收款凭证", 100)
    request_id = text_field(p, "requestId", "退款申请编号", 80)
    reason = text_field(p, "reason", "退款原因", 300)
    amount = currency_amount(p.get("amount"), "退款金额", zero=False)
    mode = p.get("mode", "manual")
    if mode not in ("manual", "channel"):
        raise ValueError("请选择退款核实方式")
    refunds = state.setdefault("refunds", [])
    for row in refunds:
        if row["requestId"] == request_id:
            if (
                row["receiptId"],
                row["residentId"],
                Decimal(str(row["amount"])),
                row["reason"],
                row["mode"],
            ) != (receipt, rid, amount, reason, mode):
                raise ValueError("申请编号已被其他退款使用")
            return "已登记该退款申请"
    origins = payment_parts(state, rid, receipt)
    if not origins:
        raise ValueError("没有可用于退款的原始收款凭证")
    original = origins[0][1]
    channel = original.get("channel") or original["method"]
    if mode == "channel" and (
        channel not in ("微信支付", "支付宝")
        or not original.get("transactionId")
        or not original.get("merchantOrder")
    ):
        raise ValueError("此笔收款没有可用于原路退回的渠道订单")
    if mode == "channel":
        from .checkout import enabled_channels

        if channel not in enabled_channels():
            raise ValueError("尚未接通此商户渠道，请先核实实际退款凭证")
        signed = any(
            r["id"] == receipt
            and r["residentId"] == rid
            and r.get("verification") == "渠道签名通知"
            and r.get("transactionId") == original.get("transactionId")
            and r.get("merchantOrder") == original.get("merchantOrder")
            for r in state.get("channelReceipts", ())
        )
        if not signed:
            raise ValueError("仅支持已通过原商户渠道验签的交易原路退款")
    prior = {}
    prior_total = {}
    for refund in refunds:
        if refund["receiptId"] == receipt and refund["status"] != "已取消":
            for part in refund["parts"]:
                key = part.get("allocationId") or part["originalId"]
                prior[key] = prior.get(key, 0) + part["cents"]
                origin = part["originalId"]
                prior_total[origin] = prior_total.get(origin, 0) + part["cents"]
    account = next((a for a in state["deposits"] if a["residentId"] == rid), None)
    remaining = cents(amount)
    parts = []
    limits = {
        row["id"]: cents(row["amount"]) - prior_total.get(row["id"], 0)
        for _, row in origins
    }
    for bucket, original_id, bill_id, available, allocation_id, tracked in _candidates(
        state, origins, account, rid, receipt
    ):
        if bill_id:
            available = min(
                available - prior.get(allocation_id or original_id, 0),
                _bill_limit(state, bill_id)
                - sum(p["cents"] for p in parts if p["billId"] == bill_id),
            )
        take = min(remaining, limits[original_id], available)
        if take > 0:
            parts.append(
                {
                    "bucket": bucket,
                    "originalId": original_id,
                    "billId": bill_id,
                    "cents": take,
                    "allocationId": allocation_id,
                    "tracked": tracked,
                }
            )
            remaining -= take
            limits[original_id] -= take
        if not remaining:
            break
    if remaining:
        raise ValueError("退款超过原交易可退金额、账单已付金额或尚未使用的预缴余额")
    _reserve_advance(account, receipt, parts, -1)
    refunds.append(
        {
            "id": new_id("rf"),
            "requestId": request_id,
            "residentId": rid,
            "receiptId": receipt,
            "amount": float(amount),
            "grossAmount": yuan(sum(cents(r["amount"]) for _, r in origins)),
            "mode": mode,
            "channel": channel,
            "method": original["method"],
            "reason": reason,
            "transactionId": original.get("transactionId", ""),
            "merchantOrder": original.get("merchantOrder", ""),
            "date": today,
            "receiptDate": original["date"],
            "actorId": actor["id"],
            "operator": actor["displayName"],
            "status": "待核实",
            "parts": parts,
        }
    )
    return f"已登记原收款凭证 {receipt} 的退款申请 ¥{amount:.2f}，待核实实际退款结果"


def resolve(state, row, actor, today, reference, *, cancel=False, refund_date=None):
    paid_on = parse_day(refund_date or today).isoformat()
    if not row.get("receiptDate", row["date"]) <= paid_on <= today:
        raise ValueError("实际退款日期须在原收款日期与今天之间")
    if row["status"] not in PENDING:
        if (
            row["status"] == ("已取消" if cancel else "已退款")
            and row.get("reference", "") == reference
            and (cancel or not refund_date or row["refundedOn"] == paid_on)
        ):
            return "已处理同一退款申请"
        raise ValueError("退款申请已经处理，请查阅原记录")
    if cancel:
        account = next(
            (a for a in state["deposits"] if a["residentId"] == row["residentId"]), None
        )
        _reserve_advance(account, row["receiptId"], row["parts"], 1)
        row["status"] = "已取消"
    else:
        for old in chain(state.get("refunds", ()), state.get("dischargeSettlements", ())):
            if (
                old.get("reference") == reference
                and old.get("channel", old.get("method")) == row["channel"]
            ):
                raise ValueError("此退款凭证已关联另一笔退款")
        for part in row["parts"]:
            value = part["cents"]
            bill_id = part["billId"]
            if bill_id:
                bill = lookup(state, "bills", bill_id, "原账单")
                if value > cents(bill["paid"]):
                    raise ValueError("原账单实收金额发生变化，请复核")
                paid = cents(bill["paid"]) - value
                bill.update(
                    paid=yuan(paid),
                    balance=yuan(cents(bill["amount"]) - paid),
                    status="部分缴费" if paid else "待缴费",
                )
            reverse = {
                "id": new_id("reversal"),
                "receiptId": row["id"],
                "refundOf": row["receiptId"],
                "residentId": row["residentId"],
                "date": paid_on,
                "amount": -yuan(value),
                "channel": row["channel"],
                "method": row["method"],
                "feeAmount": 0,
                "netAmount": -yuan(value),
                "refundReference": reference,
            }
            if bill_id:
                if part.get("allocationId"):
                    source = lookup(
                        state, "payments", part["allocationId"], "预缴冲抵凭证"
                    )
                    state["payments"].insert(
                        0,
                        {
                            "id": new_id("offset-return"),
                            "billId": bill_id,
                            "residentId": row["residentId"],
                            "date": paid_on,
                            "amount": -yuan(value),
                            "method": source["method"],
                            "refundId": row["id"],
                            "reverses": source["id"],
                            "sourceAllocations": [
                                {"receiptId": row["receiptId"], "amount": -yuan(value)}
                            ],
                        },
                    )
                    reverse["originBillId"] = bill_id
                else:
                    reverse["billId"] = bill_id
            state[part["bucket"]].insert(0, reverse)
        row["status"] = "已退款"
        row["refundedOn"] = paid_on
    row.update(
        reference=reference,
        resolvedOn=today,
        reviewerId=actor["id"],
        reviewer=actor["displayName"],
    )
    return "已取消并释放退款占用" if cancel else "已核实退款，冲正流水已入账"


def command(state, action, p, actor, today):
    if action == "ops.requestRefund":
        return request(state, p, actor, today)
    if not state.get("refunds"):
        raise ValueError("找不到退款申请")
    row = lookup(state, "refunds", p.get("refundId"), "退款申请")
    if row["residentId"] != p.get("residentId"):
        raise ValueError("退款凭证与长辈不一致")
    if row["mode"] != "manual":
        raise ValueError("渠道退款须等待商户接口核实结果")
    cancel = action == "ops.cancelRefund"
    if not cancel and p.get("verified") is not True:
        raise ValueError("请核实实际退款并保留凭证")
    reference = (
        "" if cancel else text_field(p, "reference", "实际退款流水或签收凭证号", 100)
    )
    return resolve(
        state,
        row,
        actor,
        today,
        reference,
        cancel=cancel,
        refund_date=p.get("refundDate"),
    )
