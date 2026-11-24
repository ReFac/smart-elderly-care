"""Invoice lines use agreed institution rates; personal income is never a charge."""

from decimal import Decimal

from .records import currency_amount, whole_number

CATEGORIES = {
    "meal": "饮食费",
    "medical": "医疗服务费",
    "medicine": "药品费",
    "supplies": "照护耗材费",
    "rehab": "康复服务费",
    "laundry": "洗护费",
    "escort": "陪诊与交通费",
    "utilities": "水电费",
    "service": "专项服务费",
    "other": "其他约定收费",
    "reduction": "费用减免",
}
UNITS = ("天", "次", "份", "件", "月", "笔")


def line(code, label, unit, qty, price, **extra):
    price = Decimal(str(price))
    amount = qty * price * (-1 if code == "reduction" else 1)
    return dict(
        code=code,
        label=label,
        unit=unit,
        quantity=qty,
        unitPrice=float(price),
        amount=float(amount),
        **extra,
    )


def invoice_lines(segments, package, extras, service_days, leave_days):
    if not isinstance(extras, list) or len(extras) > 100:
        raise ValueError("请选择不超过 100 项的费用明细")
    lines = []
    for seg in segments:
        period = dict(start=seg["start"], end=seg["end"])
        lines.append(
            line("room", "房间床位费", "天", seg["days"], seg["bedFee"], **period)
        )
        lines.append(
            line(
                "care",
                "护理费",
                "天",
                seg["days"] - seg["leaveDays"],
                seg["careFee"],
                **period,
            )
        )
    if package:
        lines.append(line("package", "月度套餐费", "月", 1, package))
    for item in extras:
        if not isinstance(item, dict) or set(item) - {
            "code",
            "label",
            "unit",
            "quantity",
            "unitPrice",
            "basis",
        }:
            raise ValueError("收费项目字段无效")
        code, unit, basis = (
            item.get("code"),
            item.get("unit"),
            item.get("basis", "quantity"),
        )
        if not isinstance(code, str) or code not in CATEGORIES or unit not in UNITS:
            raise ValueError("请选择有效的收费类别和计量单位")
        if (
            basis not in ("quantity", "presentDays", "serviceDays")
            or basis != "quantity"
            and unit != "天"
        ):
            raise ValueError("按入住或在院天数计费的单位须为天")
        label = item.get("label", "")
        if (
            not isinstance(label, str)
            or len(label.strip()) > 80
            or any(ord(c) < 32 for c in label)
        ):
            raise ValueError("明细名称不能超过 80 字")
        label = label.strip()
        if code == "other" and not label:
            raise ValueError("请注明其他约定收费的具体项目")
        if basis == "quantity":
            qty = whole_number(item.get("quantity"), "计费数量")
        else:
            qty = service_days if basis == "serviceDays" else service_days - leave_days
        if qty > 100000:
            raise ValueError("计费数量超出范围")
        price = currency_amount(item.get("unitPrice"), "约定单价")
        entry = line(code, label or CATEGORIES[code], unit, qty, price, basis=basis)
        currency_amount(abs(Decimal(str(entry["amount"]))), "分项金额")
        lines.append(entry)
    return lines
