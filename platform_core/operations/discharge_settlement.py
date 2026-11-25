"""Close a discharged resident's ledger against verified off-system refund evidence."""

from decimal import Decimal

from .records import currency_amount, get_resident, new_id, text_field


def settle(state, payload, actor, today):
    person = get_resident(state, payload)
    if person.get("status") != "已退住" or not person.get("dischargedAt"):
        raise ValueError("仅可为已经办理退住的长辈结算")
    rid = person["id"]
    bills = [bill for bill in state["bills"] if bill["residentId"] == rid]
    if any(bill["balance"] for bill in bills):
        raise ValueError("请先核对并结清所有待缴账单")
    account = next((a for a in state["deposits"] if a["residentId"] == rid), None)
    advance = Decimal(str(account["amount"])) if account else Decimal(0)
    offsets = {}
    for row in state["payments"]:
        key = row.get("securityBillId")
        if key:
            offsets[key] = offsets.get(key, Decimal(0)) + Decimal(str(row["amount"]))
    securities = []
    for bill in bills:
        if bill.get("kind") == "security":
            paid = Decimal(str(bill["paid"])) - Decimal(
                str(bill.get("refundedSecurity", 0))
            )
            balance = paid - offsets.get(bill["id"], Decimal(0))
            if balance < 0:
                raise ValueError("押金凭证存在差额，请核对账目")
            if balance:
                securities.append((bill, balance))
    security_total = sum((amount for _, amount in securities), Decimal(0))
    total = advance + security_total
    if total != currency_amount(payload.get("amount"), "核对退款金额"):
        raise ValueError("退款金额与可退预缴、押金的合计不一致，请重新核对")
    closed = state.setdefault("dischargeSettlements", [])
    if not total and any(
        r["residentId"] == rid and r["dischargedAt"] == person["dischargedAt"]
        for r in closed
    ):
        raise ValueError("本次退住已完成结算")
    method, reference = "", ""
    if total:
        method = payload.get("method")
        if method not in ("现金", "银行转账", "微信支付", "支付宝", "银联刷卡"):
            raise ValueError("请选择实际退款渠道")
        reference = text_field(payload, "reference", "退款流水或签收凭证号", 100)
        if any(
            r.get("method") == method and r.get("reference") == reference
            for r in closed
        ):
            raise ValueError("这张退款凭证已经登记")
    if account:
        account["amount"] = 0
    for bill, value in securities:
        bill["refundedSecurity"] = float(
            Decimal(str(bill.get("refundedSecurity", 0))) + value
        )
    closed.append(
        {
            "id": new_id("settle"),
            "residentId": rid,
            "dischargedAt": person["dischargedAt"],
            "date": today,
            "operator": actor["displayName"],
            "actorId": actor["id"],
            "advance": float(advance),
            "security": float(security_total),
            "amount": float(total),
            "method": method,
            "reference": reference,
            "bills": [b["id"] for b in bills],
            "securityBills": {b["id"]: float(v) for b, v in securities},
        }
    )
    return f"完成{person['name']}的退住结算，登记已退金额 ¥{total:.2f}"
