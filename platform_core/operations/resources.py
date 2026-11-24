"""库存流水、可用存量与人员排班。"""

import unicodedata

from .records import lookup, new_id, parse_day, text_field, whole_number


def item_key(name, unit):
    return tuple(
        unicodedata.normalize("NFKC", field).strip().casefold()
        for field in (name, unit)
    )


def add_item(state, payload, today):
    name = text_field(payload, "name", "物资名称", 80)
    unit = text_field(payload, "unit", "计量单位", 16)
    minimum = whole_number(payload.get("minimum"), "库存下限", zero=True)
    if "quantity" in payload:
        raise ValueError("请在建档后通过入库流水登记实际数量")
    key = item_key(name, unit)
    if any(item_key(row["name"], row["unit"]) == key for row in state["inventory"]):
        raise ValueError("相同名称和单位的物资已建档")
    state["inventory"].append(
        dict(id=new_id("stock"), name=name, unit=unit, minimum=minimum, quantity=0)
    )
    return f"新建物资品目{name}（{unit}）"


def record_stock(state, payload, today):
    item = lookup(state, "inventory", payload.get("itemId"), "物资")
    quantity = whole_number(payload.get("quantity"), "物资数量")
    direction = payload.get("type")
    if direction not in ("出库", "入库"):
        raise ValueError("请选择出库或入库")
    if direction == "出库" and quantity > item["quantity"]:
        raise ValueError("库存不足，无法出库")
    note = payload.get("note", "")
    if not isinstance(note, str) or len(note) > 160:
        raise ValueError("备注最多 160 字")
    item["quantity"] += quantity if direction == "入库" else -quantity
    state["transactions"].insert(
        0,
        dict(
            id=new_id("mov"),
            itemId=item["id"],
            type=direction,
            quantity=quantity,
            date=today,
            note=note.strip(),
        ),
    )
    return f"{item['name']}{direction} {quantity} {item['unit']}"


def assign_shift(state, payload, today):
    staff = text_field(payload, "staff", "员工姓名", 40)
    area = text_field(payload, "area", "工作区域", 60)
    when = parse_day(payload.get("date")).isoformat()
    period = payload.get("period")
    if period not in ("早班", "中班", "夜班"):
        raise ValueError("请选择有效班次")
    if any(
        (s["staff"], s["date"], s["period"]) == (staff, when, period)
        for s in state["shifts"]
    ):
        raise ValueError("该员工在此班次已有排班")
    state["shifts"].insert(
        0,
        dict(
            id=new_id("shift"),
            staff=staff,
            date=when,
            period=period,
            area=area,
            **({"campusId": payload["campusId"]} if "campusId" in payload else {}),
        ),
    )
    return f"为{staff}安排 {when} {period} · {area}"
