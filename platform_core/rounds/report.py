"""Collect nursing workload and independently attributable facts for a resident’s daily brief."""

from datetime import timedelta
from statistics import median

from . import narrative


def observation_trend(db, rid, bed, day, since_stay):
    # Match clock hours and physical location to avoid comparing night-only and day-only samples.
    since = max((day - timedelta(days=7)).isoformat(), since_stay)
    rows = db.execute(
        """SELECT day,hour,events,minutes,source,attribution FROM rounds_observations
           WHERE resident=? AND bed=? AND day BETWEEN ? AND ?
           ORDER BY day,hour""",
        (rid, bed, since, day.isoformat()),
    )
    by_day = {}
    for observed, hour, count, minutes, source, attribution in rows:
        by_day.setdefault(observed, {})[hour] = (count, minutes, source, attribution)
    recorded = by_day.pop(day.isoformat(), {})
    today = {h: sample for h, sample in recorded.items() if sample[1] >= 30}
    minutes = sum(sample[1] for sample in today.values())
    count = sum(sample[0] for sample in today.values())
    comparable = {
        date: hours
        for date, hours in by_day.items()
        if today
        and all(
            h in hours and hours[h][1] >= 30 and hours[h][2:] == sample[2:]
            for h, sample in today.items()
        )
        and sum(hours[h][1] for h in today) >= 60
    }
    result = {
        "status": "insufficient",
        "count": count,
        "recordedMinutes": sum(sample[1] for sample in recorded.values()),
        "recordedCount": sum(sample[0] for sample in recorded.values()),
        "observedMinutes": minutes,
        "historyDays": len(comparable),
        "hours": sorted(today),
        "rate": round(count * 60 / minutes, 2) if minutes else None,
        "baseline": None,
        "noticeable": False,
        "historyDates": sorted(comparable),
        "coverageNote": "仅比较当前床位、相同时段、相同来源与归属方式的已核对记录。每小时至少覆盖 30 分钟，各比较日至少 60 分钟，过去 7 天至少 3 个可比日。",
    }
    if minutes < 60 or len(comparable) < 3:
        return result
    # Standardize each past day's rate to today's distribution of observed minutes.
    daily = []
    for hours in comparable.values():
        weighted_events = sum(
            hours[h][0] / hours[h][1] * sample[1] for h, sample in today.items()
        )
        daily.append(weighted_events * 60 / minutes)
    reference = median(daily)
    result.update(
        baseline=round(reference, 2),
        noticeable=count * 60 / minutes >= max(reference * 1.5, reference + 2),
        status="elevated" if count * 60 / minutes > reference + 1e-9 else "stable",
    )
    return result


def in_stay(row, resident):
    bed = row.get("checkedBedId") or row.get("executionBedId") or row.get("bedId")
    if bed and bed != resident.get("bedId"):
        return False
    if row.get("date", "") >= resident["_fromDay"]:
        return True
    # A dated transfer lacks the exact move time. A bedside check at the new bed disambiguates that day.
    return bool(bed and row.get("date") == resident["_transferDay"])


def build(db, state, resident, now):
    rid = resident["id"]
    day = now.date().isoformat()
    tasks = sorted(
        (
            r
            for r in state["tasks"]
            if r["residentId"] == rid
            and r["date"] == day
            and r["status"] != "已取消"
            and in_stay(r, resident)
        ),
        key=lambda r: (r.get("time", ""), r["id"]),
    )
    pending = [r for r in tasks if r["status"] == "待执行"]
    overdue = [
        r for r in pending if r.get("time") and r["time"] < now.strftime("%H:%M")
    ]
    completed = [r for r in tasks if r["status"] == "已完成"]
    today = {
        "planned": len(tasks),
        "completed": len(completed),
        "pending": len(pending),
        "overdue": len(overdue),
    }
    carry = any(
        row["residentId"] == rid
        and row["date"] < day
        and row["status"] == "待执行"
        and in_stay(row, resident)
        for row in state["tasks"]
    )
    pending_review = any(
        row["residentId"] == rid
        and row.get("date", "") <= day
        and row["status"] == "待复核"
        and in_stay(row, resident)
        for row in state.get("vitals", ())
    )
    cough = observation_trend(
        db, rid, resident["bedId"], now.date(), resident["_fromDay"]
    )
    daily = narrative.daily_facts(db, state, resident, now)
    clinical, suggestions = narrative.clinical_facts(db, state, resident, now, cough)
    signals = [
        code
        for code, present in (
            ("pending", bool(pending)),
            ("carry", carry),
            ("vital", pending_review),
            ("cough", cough["noticeable"]),
        )
        if present
    ]
    if not daily:
        daily = [
            {
                "day": day,
                "time": "",
                "text": "这两天还没有已核实的起居、用餐或活动记录。",
                "permission": "care",
                "evidence": [],
            }
        ]
    return {
        "residentId": rid,
        "stayId": resident["_stayId"],
        "bedId": resident["bedId"],
        "day": day,
        "format": "daily-life-v2",
        "today": today,
        "staffSignals": signals,
        "dailyFacts": daily,
        "clinicalFacts": clinical,
        "suggestions": suggestions,
        "cough": cough,
    }


def attention(report):
    if "staffSignals" in report:
        return report["staffSignals"]
    # Persisted reports created before daily-life summaries derived inbox signals from suggestions.
    evidence = [ref for item in report["suggestions"] for ref in item["evidence"]]
    return [
        code
        for code, present in (
            ("pending", report["today"]["pending"] > 0),
            (
                "carry",
                any(
                    r["kind"] == "task" and r["date"] < report["day"] for r in evidence
                ),
            ),
            ("vital", any(r["kind"] == "vital" for r in evidence)),
            ("cough", report["cough"]["status"] == "elevated"),
        )
        if present
    ]
