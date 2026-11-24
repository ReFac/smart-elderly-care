"""本地民政月度草稿和完整性检查。"""

from copy import deepcopy

from .billing import CARE_RATES
from .records import lookup, month_bounds, new_id, parse_day, text_field


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
    if report.get("stage") in ("待回执", "已受理"):
        raise ValueError("本期报送已送出，请核对现有版本回执")
    version = report.get("version", 1)
    if report.get("stage") == "已退回":
        version += 1
    eligible = {r["residentId"] for r in rows}
    start, through = first.isoformat(), cutoff.isoformat()
    tasks = [
        t
        for t in state.get("tasks", [])
        if t.get("residentId") in eligible and t.get("status") != "已取消"
    ]
    scheduled = [t for t in tasks if start <= t.get("date", "") <= through]
    completed = [
        t
        for t in tasks
        if t.get("status") == "已完成"
        and start <= (t.get("completedAt") or t.get("date", "")) <= through
    ]
    report.update(
        version=version,
        stage="草稿",
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
        serviceMetrics=dict(
            scheduledTasks=len(scheduled),
            completedTasks=len(completed),
            servedResidents=len({t["residentId"] for t in completed}),
        ),
        checks=["入住与退住日期", "姓名与护理等级", "当前在住床位", "退住日期一致性"],
    )
    return f"生成 {month} 民政报送本地草稿，归集 {len(rows)} 条，发现 {len(issues)} 项待补正"


def submit_report(state, p, today):
    report = lookup(state, "reports", p.get("reportId"), "报送记录")
    if (
        report.get("stage", "草稿") != "草稿"
        or report["status"] != "已校验"
        or report.get("issues")
    ):
        raise ValueError("只可登记已通过校验且尚未送出的草稿")
    if "serviceMetrics" not in report:
        raise ValueError("请重新生成本月草稿，核对照护运营汇总后登记送出")
    recipient = text_field(p, "recipient", "接收机构", 80)
    ref = text_field(p, "submissionRef", "送出凭证编号", 100)
    if any(
        s["recipient"] == recipient and s["submissionRef"] == ref
        for r in state["reports"]
        for s in r.get("submissions", [])
    ):
        raise ValueError("接收方的送出凭证编号已登记")
    version = report.setdefault("version", 1)
    snapshot = deepcopy(
        {
            k: report[k]
            for k in (
                "id",
                "month",
                "version",
                "cutoff",
                "createdAt",
                "recordCount",
                "summary",
                "serviceMetrics",
                "rows",
                "checks",
                "issues",
                "status",
            )
        }
    )
    report.setdefault("submissions", []).append(
        dict(
            version=version,
            recipient=recipient,
            submissionRef=ref,
            sentOn=today,
            snapshot=snapshot,
        )
    )
    report["stage"] = "待回执"
    return f"登记 {report['month']} 第 {version} 版报送凭证，等待接收方回执"


def report_receipt(state, p, today):
    report = lookup(state, "reports", p.get("reportId"), "报送记录")
    if report.get("stage") != "待回执":
        raise ValueError("报送记录不在等待回执状态")
    outcome = p.get("outcome")
    if outcome not in ("已受理", "已退回"):
        raise ValueError("请选择接收方回执结果")
    submission = report["submissions"][-1]
    ref = text_field(p, "receiptRef", "回执编号", 100)
    if any(
        s.get("receiptRef") == ref and s["recipient"] == submission["recipient"]
        for r in state["reports"]
        for s in r.get("submissions", [])
    ):
        raise ValueError("该接收方回执编号已登记")
    note = text_field(p, "note", "回执说明", 500)
    submission.update(receiptRef=ref, receiptDate=today, outcome=outcome, note=note)
    report["stage"] = outcome
    return f"登记 {report['month']} 第 {submission['version']} 版民政回执：{outcome}"
