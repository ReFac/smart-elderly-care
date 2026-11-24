"""运营单据的字段约束、日期区间和金额解析。"""

import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4


CENT = Decimal("0.01")


def new_id(prefix):
    return f"{prefix}-{uuid4().hex[:16]}"


def text_field(payload, key, label, limit=160):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"请填写有效的{label}（最多 {limit} 字）")
    return value.strip()


def currency_amount(value, label, *, zero=True):
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite()
            or amount < 0
            or amount > 99_999_999
            or amount != amount.quantize(CENT)
        ):
            raise ValueError
        if not zero and amount == 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        raise ValueError(f"{label}须为有效金额，最多两位小数") from None
    return amount


def whole_number(value, label, *, zero=False):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,9}", str(value)):
        raise ValueError(f"{label}须为整数")
    number = int(value)
    if number == 0 and not zero:
        raise ValueError(f"{label}必须大于零")
    return number


def parse_day(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
    ):
        raise ValueError("日期须采用 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("请填写有效日期") from None


def month_bounds(month, today):
    if not isinstance(month, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError("请选择账期月份")
    first = parse_day(month + "-01")
    if first > parse_day(today):
        raise ValueError("不能生成未来月份的记录")
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def lookup(state, table, row_id, label):
    for row in state[table]:
        if row["id"] == row_id:
            return row
    raise ValueError(f"找不到{label}")


def get_resident(state, payload):
    return lookup(state, "residents", payload.get("residentId"), "长者档案")
