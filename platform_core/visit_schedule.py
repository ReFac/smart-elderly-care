"""Half-hour reception seats in China Standard Time, updated inside a workspace transaction."""

import re
from datetime import date
from uuid import uuid4
from zoneinfo import ZoneInfo


LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
KINDS = ("visit", "callback")
MAX_CAPACITY = 32


def _local(now):
    if now.tzinfo is None:
        return now.replace(tzinfo=LOCAL_ZONE)
    return now.astimezone(LOCAL_ZONE)


def _day(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise ValueError("请选择有效日期，格式为 YYYY-MM-DD") from None
    return value


def _minute(value, *, ending=False):
    if ending and value == "24:00":
        return 1440
    if not isinstance(value, str) or not re.fullmatch(
        r"([01][0-9]|2[0-3]):(00|30)", value
    ):
        raise ValueError("预约起止时间须为整点或半点")
    return int(value[:2]) * 60 + int(value[3:])


def _clock(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _bookable_from(now):
    # At 14:00:00 the 14:00 slot can still be booked. At 14:00:01 it has started.
    minute = now.hour * 60 + now.minute + bool(now.second or now.microsecond)
    return now.date().isoformat(), minute


def _campus_bookings(state, campus_id):
    return (
        row for row in state.get("visitBookings", ()) if row["campusId"] == campus_id
    )


def _policy(state, campus_id):
    return next(
        (
            row
            for row in state.get("visitSchedulePolicies", ())
            if row["id"] == campus_id
        ),
        None,
    )


def capacity(state, campus_id):
    row = _policy(state, campus_id)
    return row["capacity"] if row else 1


def configure(state, campus_id, capacity, now):
    """Keep all ongoing and upcoming reservations on their confirmed seats."""
    if type(capacity) is not int or not 1 <= capacity <= MAX_CAPACITY:
        raise ValueError(f"请选择 1 至 {MAX_CAPACITY} 个并行接待席位")
    local_now = _local(now)
    current = (local_now.date().isoformat(), local_now.strftime("%H:%M"))
    for row in _campus_bookings(state, campus_id):
        if (
            row["status"] == "confirmed"
            and row["seat"] > capacity
            and (row["date"], row["end"]) > current
        ):
            raise ValueError("要减少的席位仍有进行中或未来的预约，请先改期或更换席位")
    policy = _policy(state, campus_id)
    if policy is None:
        policy = {"id": campus_id, "campusId": campus_id}
        state.setdefault("visitSchedulePolicies", []).append(policy)
    policy.update(capacity=capacity, updatedAt=local_now.isoformat(timespec="seconds"))
    return "更新本院区并行接待席位数"


def _finish(row, status, timestamp, actor_id):
    row.update(status=status, closedAt=timestamp, closedBy=actor_id)


def reserve(state, campus_id, lead_id, payload, now, actor_id):
    """The caller checks campus access and telephone confirmation before assigning a seat."""
    day = _day(payload.get("date"))
    start, end = payload.get("start"), payload.get("end")
    start_minute = _minute(start)
    if start_minute >= _minute(end, ending=True):
        raise ValueError("预约结束时间须晚于开始时间")
    local_now = _local(now)
    if (day, start_minute) < _bookable_from(local_now):
        raise ValueError("请选择尚未开始的预约时间")
    kind = payload.get("kind")
    if kind not in KINDS:
        raise ValueError("请选择来访或电话回访")
    limit = capacity(state, campus_id)
    chosen = payload.get("seat")
    if chosen is not None and (type(chosen) is not int or not 1 <= chosen <= limit):
        raise ValueError("请选择本院区有效的接待席位")
    previous = None
    occupied = set()
    for row in _campus_bookings(state, campus_id):
        if row["status"] != "confirmed":
            continue
        same_lead = row["leadId"] == lead_id
        if same_lead and row["kind"] == kind:
            previous = row
        elif row["date"] == day and row["start"] < end and start < row["end"]:
            if same_lead:
                raise ValueError("这位客户在所选时段已有其他预约")
            occupied.add(row["seat"])
    if chosen is None:
        if previous and previous["seat"] <= limit and previous["seat"] not in occupied:
            chosen = previous["seat"]
        else:
            chosen = next(
                (seat for seat in range(1, limit + 1) if seat not in occupied), None
            )
    if chosen is None or chosen in occupied:
        raise ValueError("所选时段没有可全程使用的接待席位，请更换时间或席位")
    if previous and (
        previous["date"],
        previous["start"],
        previous["end"],
        previous["seat"],
    ) == (day, start, end, chosen):
        return previous
    timestamp = local_now.isoformat(timespec="seconds")
    booking = {
        "id": uuid4().hex,
        "campusId": campus_id,
        "leadId": lead_id,
        "date": day,
        "start": start,
        "end": end,
        "seat": chosen,
        "kind": kind,
        "status": "confirmed",
        "confirmedAt": timestamp,
        "confirmedBy": actor_id,
    }
    if previous:
        _finish(previous, "rescheduled", timestamp, actor_id)
        booking["replacesId"] = previous["id"]
    state.setdefault("visitBookings", []).append(booking)
    return booking


def close(state, campus_id, lead_id, kind, status, now, actor_id):
    if status not in ("cancelled", "completed") or (
        kind is not None and kind not in KINDS
    ):
        raise ValueError("预约类别或处理结果无效")
    changed = []
    timestamp = _local(now).isoformat(timespec="seconds")
    for row in _campus_bookings(state, campus_id):
        if (
            row["leadId"] == lead_id
            and row["status"] == "confirmed"
            and (kind is None or kind == row["kind"])
        ):
            _finish(row, status, timestamp, actor_id)
            changed.append(row)
    return changed


def _occupied_end(row):
    """Keep elapsed slots visible when staff release the rest of an appointment early."""
    end = _minute(row["end"], ending=True)
    if row["status"] == "confirmed":
        return end
    closed = row["closedAt"]
    if row["date"] < closed[:10]:
        return end
    if row["date"] > closed[:10]:
        return 0
    elapsed = int(closed[11:13]) * 60 + int(closed[14:16])
    if int(closed[17:19]):
        elapsed += 1
    return min(end, elapsed)


def day_view(state, campus_id, day, now):
    day = _day(day)
    local_now = _local(now)
    rows = [row for row in _campus_bookings(state, campus_id) if row["date"] == day]
    rows.sort(key=lambda r: (r["start"], r["seat"], r["confirmedAt"]))
    limit = capacity(state, campus_id)
    occupied = [(row, _occupied_end(row)) for row in rows]
    columns = max(
        [limit] + [row["seat"] for row, end in occupied if end > _minute(row["start"])]
    )
    slots = []
    earliest = _bookable_from(local_now)
    for start in range(0, 1440, 30):
        in_future = (day, start) >= earliest
        slots.append(
            {
                "start": _clock(start),
                "end": _clock(start + 30),
                "seats": [None] * columns,
                "bookable": in_future,
            }
        )
    for row, end in occupied:
        for start in range(_minute(row["start"]), end, 30):
            slots[start // 30]["seats"][row["seat"] - 1] = row["id"]
    for slot in slots:
        slot["bookable"] = slot["bookable"] and None in slot["seats"][:limit]
    return {
        "campusId": campus_id,
        "date": day,
        "capacity": limit,
        "displayCapacity": columns,
        "slots": slots,
        "bookings": rows,
    }
