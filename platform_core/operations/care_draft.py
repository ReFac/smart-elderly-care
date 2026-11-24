"""Produce an individual, read-only care plan from a reviewed assessment and its plan."""

from ..care.plans import SERVICE_ITEMS


def assessment_facts(row):
    """Expose only checked care observations and the public result of a completed scale."""
    scale = row.get("scale") or {}
    observations = row.get("observations") or {}
    return {
        "assessedOn": scale.get("assessedOn") or row["date"],
        "historyOnly": bool(row.get("historyOnly")),
        "assignee": row.get("assignee") or "",
        "supportNeeds": "、".join(
            key for key in SERVICE_ITEMS if observations.get(key) == "需协助"
        ),
        "serviceItems": "、".join(
            item
            for key, item in SERVICE_ITEMS.items()
            if observations.get(key) == "需协助"
        ),
        "pendingNeeds": "、".join(
            key for key in SERVICE_ITEMS if observations.get(key) == "待观察"
        ),
        "scaleGrade": scale.get("gradeName") or "",
    }


def plan_facts(row):
    return {"serviceItems": "、".join(row.get("items") or ())}


def draft(state, resident, today, cite):
    rid = resident["id"]
    evidence = [cite("residents", "长者档案", [resident], resident["level"])]
    lines = [f"档案护理等级为{resident['level']}。"]
    assessments = []
    for row in state.get("assessments", ()):
        if row["residentId"] != rid or row["date"] > today:
            continue
        item = row if "assessedOn" in row else {**row, **assessment_facts(row)}
        if not item.get("historyOnly") and item["assessedOn"] <= today:
            assessments.append(item)
    if assessments:
        # Equal-day assessments are appended in order. Exclude backfilled historical forms.
        latest = max(reversed(assessments), key=lambda a: a["assessedOn"])
        matched = next(
            (
                p
                for p in reversed(state.get("plans", ()))
                if p["residentId"] == rid
                and p.get("assessmentId") == latest["id"]
                and p.get("date", "") <= today
                and p.get("status") in ("待复核", "已派发")
            ),
            None,
        )
        text = f"{latest['assessedOn']} 评估 · {latest['level']}"
        if latest.get("scaleGrade"):
            text += " · 量表结果" + latest["scaleGrade"]
        needs = latest.get("supportNeeds") or "尚无已确认的协助项目"
        lines.extend([text + "。", f"已确认生活需求：{needs}。"])
        if latest.get("pendingNeeds"):
            lines.append(f"尚待观察：{latest['pendingNeeds']}。")
        evidence.append(
            cite("assessments", "最近评估与生活需求", [latest], text + " · " + needs)
        )
        assignee = latest.get("assignee") or "待护理负责人指定"
        services = latest.get("serviceItems") or "待评估人员确认"
        review = latest.get("reviewDate") or "待评估人员登记"
        if matched:
            items = (
                matched["serviceItems"]
                if "serviceItems" in matched
                else plan_facts(matched)["serviceItems"]
            )
            services = items or services
            assignee = matched.get("assignee") or assignee
            review = matched.get("reviewDate") or review
            evidence.append(
                cite(
                    "plans",
                    "关联照护计划",
                    [matched],
                    f"{matched['status']} · {services} · {assignee} · 复评 {review}",
                )
            )
        lines.append(f"建议服务：{services}。责任人：{assignee}。复评日：{review}。")
    else:
        lines.append(
            "尚无已登记的有效评估，请先核实生活需求、服务项目、责任人及复评日。"
        )
    due = sorted(
        (
            t
            for t in state.get("tasks", ())
            if t["residentId"] == rid and t["status"] == "待执行" and t["date"] <= today
        ),
        key=lambda t: (t["date"], t.get("time", "")),
    )
    lines.append(f"本日到期待办 {len(due)} 项。")
    if due:
        item = due[0]
        lines.append(
            f"优先核对「{item['title']}」（{item['date']}，{item['assignee']}）。"
        )
    evidence.append(cite("tasks", "到期工单（最早 10 项）", due[:10], f"{len(due)} 项"))
    return rid, f"{resident['name']}的健康照护计划草稿", "".join(lines), evidence
