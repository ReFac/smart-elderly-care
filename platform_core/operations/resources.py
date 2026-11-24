"""库存流水、可用存量与人员排班。"""

import unicodedata

from .records import lookup, new_id, parse_day, text_field, whole_number


ITEM_FIELDS = ("name", "unit", "brand", "specification")
DRAFT_FIELDS = {*ITEM_FIELDS, "minimum", "openingQuantity"}


def item_key(name, unit, brand="", specification=""):
    return tuple(
        " ".join(unicodedata.normalize("NFKC", field).split()).casefold()
        for field in (name, unit, brand, specification)
    )


def identity(item):
    return item_key(*(item.get(field, "") for field in ITEM_FIELDS))


def _optional(payload, key, label):
    value = payload.get(key, "")
    if isinstance(value, str) and not value.strip():
        return ""
    return text_field(payload, key, label, 80)


def item_draft(payload):
    if "quantity" in payload:
        raise ValueError("请用期初入库字段登记实际数量")
    name = text_field(payload, "name", "物资名称", 80)
    unit = text_field(payload, "unit", "计量单位", 16)
    minimum = whole_number(payload.get("minimum"), "库存下限", zero=True)
    opening = whole_number(payload.get("openingQuantity", 0), "期初入库数量", zero=True)
    return dict(
        name=name,
        unit=unit,
        brand=_optional(payload, "brand", "品牌"),
        specification=_optional(payload, "specification", "容量或规格"),
        minimum=minimum,
        openingQuantity=opening,
    )


def _check_duplicate(state, proposed, item_id=None):
    key = identity(proposed)
    if any(row["id"] != item_id and identity(row) == key for row in state["inventory"]):
        raise ValueError("相同名称、单位、品牌和规格的物资已建档")


def add_item(state, payload, today):
    proposed = item_draft(payload)
    _check_duplicate(state, proposed)
    quantity = proposed.pop("openingQuantity")
    item = dict(id=new_id("stock"), **proposed, quantity=0)
    state["inventory"].append(item)
    if quantity:
        record_stock(
            state,
            {
                "itemId": item["id"],
                "type": "入库",
                "quantity": quantity,
                "note": "建档期初入库",
            },
            today,
        )
    return f"新建物资品目{item['name']}（{item['unit']}）"


def edit_item(state, payload, today):
    if set(payload) != {"itemId", "brand", "specification"}:
        raise ValueError("请选择品目并检查品牌和规格")
    item = lookup(state, "inventory", payload["itemId"], "物资")
    updates = dict(
        brand=_optional(payload, "brand", "品牌"),
        specification=_optional(payload, "specification", "容量或规格"),
    )
    _check_duplicate(state, {**item, **updates}, item["id"])
    item.update(updates)
    return f"已更新物资品目「{item['name']}」的品牌和规格"


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
            **({"campusId": payload["campusId"]} if "campusId" in payload else {}),
        ),
    )
    return f"为{staff}安排 {when} {period}"
