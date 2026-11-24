"""共享档案约束、日期与字段校验。"""

from datetime import date, timedelta
from uuid import uuid4


LEVELS = ("自理", "半失能", "失能")


def text_field(value, label, *, required=False, limit=1000):
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError(f"请检查{label}的文本长度（最多 {limit} 字）。")
    value = value.strip()
    if required and not value:
        raise ValueError(f"请填写{label}。")
    return value


def required_field(payload, key, label):
    return text_field(payload.get(key), label, required=True)


def iso_date(value, label):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{label}须为有效日期。") from None


def offset_date(day, days):
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def care_level(value):
    if value not in LEVELS:
        raise ValueError("请选择自理、半失能或失能。")
    return value


def lookup(state, collection, row_id):
    for row in state[collection]:
        if row["id"] == row_id:
            return row
    raise ValueError("所选记录不存在，请刷新后重试。")


def get_resident(state, resident_id):
    record = lookup(state, "residents", resident_id)
    if record["status"] != "在住":
        raise ValueError("该长者已退住。")
    return record


def append_record(state, collection, **fields):
    row = {"id": uuid4().hex, **fields}
    state[collection].append(row)
    return row
