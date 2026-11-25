"""Physical custody receipts for a resident's own drugs, separate from prescriptions."""
from decimal import Decimal, InvalidOperation
from uuid import UUID

from .records import append_record, get_resident, iso_date, text_field

SOURCES = ("家属交付", "长辈自带", "医疗机构", "药房配送", "其他")
UNITS = ("盒", "瓶", "支", "板", "片", "袋", "贴", "粒", "毫升", "克", "套")


def quantity(value):
    if isinstance(value, bool) or len(str(value)) > 20:
        raise ValueError("请填写有效药品数量")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("请填写有效药品数量") from None
    if not number.is_finite() or not 0 < number <= 1000000 or number.as_tuple().exponent < -3:
        raise ValueError("药品数量须为正数，最多三位小数")
    return format(number.normalize(), "f")


def receive(state, p, today):
    person = get_resident(state, p.get("residentId"))
    if not person.get("bedId"):
        raise ValueError("请核对当前床位后再交接药品")
    try:
        key = str(UUID(p["requestId"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("请重新打开登记单") from None
    if p.get("source") not in SOURCES or p.get("unit") not in UNITS:
        raise ValueError("请选择交付来源及数量单位")
    record = {
        "residentId": person["id"], "source": p["source"], "unit": p["unit"],
        "quantity": quantity(p.get("quantity")),
        "expiry": iso_date(p["expiry"], "有效期") if p.get("expiry") else "",
    }
    for name, label, limit, required in (
        ("name", "药品全名", 120, True), ("specification", "剂型与规格", 120, True),
        ("sender", "交付人", 80, True), ("lot", "生产批号", 80, False),
        ("note", "交接备注", 500, False),
    ):
        record[name] = text_field(p.get(name), label, required=required, limit=limit)
    prior = next((r for r in state["medicationReceipts"] if r["requestId"] == key), None)
    if prior:
        if prior["operatorId"] != p["operatorId"] or any(prior[k] != v for k, v in record.items()):
            raise ValueError("同一登记单内容已变更，请重新核对")
        return "该药品交接单已经登记"
    append_record(state, "medicationReceipts", **record, requestId=key, bedId=person["bedId"],
                  date=today, receivedAt=p["nowLocal"], operator=p["operator"], operatorId=p["operatorId"])
    return f"登记{person['name']}的药品交接：{record['name']} {record['quantity']}{record['unit']}"
