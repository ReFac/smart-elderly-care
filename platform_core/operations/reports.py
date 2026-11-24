"""本地民政月度草稿和完整性检查。"""

from .billing import CARE_RATES
from .records import month_bounds, new_id, parse_day


def generate_report(state, payload, today):
    month = payload.get("month")
    first, last = month_bounds(month, today)
    cutoff = min(last, parse_day(today))
    rows, issues = [], []
    for resident in state["residents"]:
        rid = resident["id"]
        try:
            arrival = parse_day(resident.get("admittedAt"))
            discharge = (
                parse_day(resident["dischargedAt"])
                if resident.get("dischargedAt")
                else None
            )
        except ValueError:
            issues.append(f"{rid} 入住或退住日期缺失或格式异常")
            continue
        if arrival > cutoff or (discharge and discharge < first):
            continue
        status = "已退住" if discharge and discharge <= cutoff else "在住"
        if discharge and discharge < arrival:
            issues.append(f"{rid} 退住早于入住")
        if not resident.get("name") or resident.get("level") not in CARE_RATES:
            issues.append(f"{rid} 姓名或护理等级缺失")
        if resident.get("status") == "已退住" and not discharge:
            issues.append(f"{rid} 缺少退住日期")
        if resident.get("status") == "在住" and not resident.get("bedId"):
            issues.append(f"{rid} 在住档案缺少床位")
        rows.append(
            dict(
                residentId=rid,
                admittedAt=arrival.isoformat(),
                dischargedAt=discharge.isoformat() if status == "已退住" else "",
                status=status,
            )
        )
    report = next((r for r in state["reports"] if r["month"] == month), None)
    if report is None:
        report = dict(id=new_id("report"), month=month)
        state["reports"].insert(0, report)
    report.update(
        status="待补正" if issues else "已校验",
        issues=issues,
        rows=rows,
        recordCount=len(rows),
        createdAt=today,
        cutoff=cutoff.isoformat(),
        summary={
            "本月入住": sum(r["admittedAt"].startswith(month) for r in rows),
            "本月退住": sum(r["dischargedAt"].startswith(month) for r in rows),
            "期末在住": sum(r["status"] == "在住" for r in rows),
        },
        checks=["入住与退住日期", "姓名与护理等级", "当前在住床位", "退住日期一致性"],
    )
    return f"生成 {month} 民政报送本地草稿，归集 {len(rows)} 条，发现 {len(issues)} 项待补正"
