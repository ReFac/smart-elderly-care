"""Evidence-based shift summaries. All calculations are local and use the institution clock."""

from datetime import timedelta
from statistics import median


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
        status="elevated" if count * 60 / minutes > reference + 1e-9 else "stable",
    )
    return result


def entry(text, rows, kind, permission="care"):
    return {
        "text": text,
        "permission": permission,
        "evidence": [
            {
                "kind": kind,
                "id": row["id"],
                "date": row.get("date") or row.get("day", ""),
            }
            for row in rows[:8]
        ],
    }


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
    changes, suggestions = [], []
    if completed:
        changes.append(
            entry(f"今日已登记完成 {len(completed)} 项照护工单。", completed, "task")
        )
    if pending:
        changes.append(
            entry(
                f"今日有 {len(pending)} 项待执行，其中 {len(overdue)} 项已过计划时刻。",
                pending,
                "task",
            )
        )
        next_task = (overdue or pending)[0]
        who = next_task.get("assignee") or "当班人员"
        suggestions.append(
            entry(
                f"请与{who}核对 {next_task.get('time', '')} 的「{next_task['title']}」执行情况。",
                [next_task],
                "task",
            )
        )
    if not tasks:
        changes.append(
            entry("今日尚无已登记照护工单，现有记录不足以判断身体状况。", [], "task")
        )
    reviews = [
        r
        for r in state.get("vitals", ())
        if r["residentId"] == rid
        and r.get("date", "") <= day
        and r["status"] == "待复核"
        and in_stay(r, resident)
    ]
    if reviews:
        changes.append(
            entry(
                f"本次入住仍有 {len(reviews)} 条体征记录仍待复核。",
                reviews,
                "vital",
                "clinical",
            )
        )
        suggestions.append(
            entry(
                "请当班护士核对待复核体征的原始记录及交班情况。",
                reviews,
                "vital",
                "clinical",
            )
        )
    carry = sorted(
        (
            r
            for r in state["tasks"]
            if r["residentId"] == rid
            and r["date"] < day
            and r["status"] == "待执行"
            and in_stay(r, resident)
        ),
        key=lambda r: r["date"],
    )
    if carry:
        changes.append(
            entry(f"此前另有 {len(carry)} 项往日工单仍标记为待执行。", carry, "task")
        )
        suggestions.append(
            entry("请交班时逐项核实往日工单，避免重复执行已完成的照护。", carry, "task")
        )
    risk = str(resident.get("risk") or "").strip()
    if risk:
        suggestions.append(
            entry(
                f"档案已登记照护风险「{risk[:120]}」，请结合现场观察逐项核对。",
                [resident],
                "resident",
                "clinical",
            )
        )
    cough = observation_trend(
        db, rid, resident.get("bedId", ""), now.date(), resident["_fromDay"]
    )
    if cough["status"] == "elevated":
        evidence = [
            {"id": f"{rid}/{date}", "date": date}
            for date in [day, *reversed(cough["historyDates"])]
        ]
        changes.append(
            entry(
                f"已核对时段的咳嗽频率为每小时 {cough['rate']} 次，高于个人近期中位数 {cough['baseline']} 次。",
                evidence,
                "reviewedCough",
                "clinical",
            )
        )
        suggestions.append(
            entry(
                "请核对设备覆盖时段、环境噪声及现场观察，再决定是否交由医护人员查看。",
                evidence,
                "reviewedCough",
                "clinical",
            )
        )
    return {
        "residentId": rid,
        "stayId": resident["_stayId"],
        "bedId": resident.get("bedId", ""),
        "day": day,
        "source": "local",
        "today": today,
        "changes": changes,
        "suggestions": suggestions,
        "cough": cough,
    }


def attention(report):
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
