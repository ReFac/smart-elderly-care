"""Validate scheduling settings and reviewed hourly observations before committing them."""

from datetime import date
import re

from .records import policy


def check_fields(body, allowed):
    if set(body) - (set(allowed) | {"revision", "comment"}):
        raise ValueError("巡查参数无效")


def update_settings(db, body, now):
    check_fields(body, ("enabled", "intervalMinutes", "defaultMode", "notifyAt"))
    enabled, interval = body.get("enabled"), body.get("intervalMinutes")
    default, notify = body.get("defaultMode"), body.get("notifyAt")
    if (
        type(enabled) is not bool
        or type(interval) is not int
        or not 5 <= interval <= 1440
    ):
        raise ValueError("巡查间隔须为 5 至 1440 分钟")
    if (
        default not in ("auto", "manual")
        or not isinstance(notify, str)
        or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", notify)
    ):
        raise ValueError("请选择生成方式和有效推送时刻")
    previous = policy(db)
    if (
        previous["enabled"],
        previous["intervalMinutes"],
        previous["defaultMode"],
        previous["notifyAt"],
    ) == (enabled, interval, default, notify):
        return False
    # Schedule one current-state sweep after enabling or changing the cadence/default.
    reschedule = enabled and (
        not previous["enabled"]
        or previous["intervalMinutes"] != interval
        or previous["defaultMode"] != default
    )
    db.execute(
        """UPDATE rounds_policy SET enabled=?,interval_min=?,default_mode=?,notify_at=?,
                  next_at=CASE WHEN ? THEN ? ELSE next_at END WHERE singleton=1""",
        (enabled, interval, default, notify, reschedule, now.isoformat()),
    )
    if not enabled:
        db.execute("DELETE FROM rounds_jobs")
    return True


def observe(db, person, user, body, now):
    check_fields(
        body,
        (
            "day",
            "hour",
            "count",
            "observedMinutes",
            "source",
            "attribution",
            "reviewed",
        ),
    )
    day, hour, count, minutes = (
        body.get(k) for k in ("day", "hour", "count", "observedMinutes")
    )
    try:
        observed = date.fromisoformat(day)
    except (TypeError, ValueError):
        raise ValueError("请输入有效的观察日期") from None
    if day != observed.isoformat() or type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("观察日期或时段无效")
    if observed > now.date() or (observed == now.date() and hour > now.hour):
        raise ValueError("不能录入未来时段")
    available = now.minute if observed == now.date() and hour == now.hour else 60
    if (
        type(minutes) is not int
        or not 1 <= minutes <= available
        or type(count) is not int
        or not 0 <= count <= 3600
    ):
        raise ValueError("请核对实际观察分钟数和咳嗽次数")
    source, attribution = body.get("source"), body.get("attribution")
    if (
        not isinstance(source, str)
        or not 1 <= len(source.strip()) <= 80
        or any(ord(c) < 32 for c in source)
    ):
        raise ValueError("请注明观测来源")
    if body.get("reviewed") is not True or attribution not in (
        "wearable",
        "staff-verified",
    ):
        raise ValueError("须核对个人佩戴设备归属或由工作人员确认是该长者的观察记录")
    if day < person["_fromDay"]:
        raise ValueError("该时段不能确定属于本次入住床位，请核对转床与入住日期")
    bed = person["bedId"]
    prior = db.execute(
        """SELECT bed,events,minutes,source,attribution FROM rounds_observations
                          WHERE resident=? AND day=? AND hour=?""",
        (person["id"], day, hour),
    ).fetchone()
    facts = (bed, count, minutes, source.strip(), attribution)
    if prior:
        if tuple(prior) == facts:
            return False
        raise ValueError("该时段已有不同的核对记录，请检查原始凭证")
    db.execute(
        "INSERT INTO rounds_observations VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            person["id"],
            bed,
            day,
            hour,
            count,
            minutes,
            source.strip(),
            attribution,
            user["id"],
            now.isoformat(),
        ),
    )
    return True
