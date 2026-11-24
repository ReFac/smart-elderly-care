"""根据可追溯的业务记录生成三类规则建议，保存人工审核结果。"""

from datetime import timedelta
from decimal import Decimal
from statistics import median

from .billing import CARE_RATES
from .care_draft import draft
from .records import get_resident, lookup, new_id, parse_day, text_field


def cite_records(source, label, rows, value):
    return dict(
        source=source, label=label, recordIds=[row["id"] for row in rows], value=value
    )


def care_review(state, payload, today):
    resident = get_resident(state, payload)
    if resident["status"] != "在住":
        raise ValueError("照护建议仅适用于在住长者")
    rid = resident["id"]
    descriptions = [f"档案护理等级为{resident['level']}。"]
    evidence = [cite_records("residents", "长者档案", [resident], resident["level"])]
    assessments = [
        a
        for a in state.get("assessments", [])
        if a["residentId"] == rid and a["date"] <= today
    ]
    if assessments:
        # 护理域按写入顺序追加，同日多次评估取最后一次。
        latest = max(reversed(assessments), key=lambda a: a["date"])
        review = latest["reviewDate"]
        descriptions.append(
            f"最近评估于 {latest['date']} 登记为{latest['level']}，复评日 {review}。"
        )
        evidence.append(
            cite_records(
                "assessments",
                "最近评估及复评",
                [latest],
                f"{latest['date']} · {latest['level']} · 复评 {review}",
            )
        )
    else:
        descriptions.append("尚无已登记评估，请核实是否需要安排评估。")
    due = sorted(
        (
            t
            for t in state.get("tasks", [])
            if t["residentId"] == rid and t["status"] == "待执行" and t["date"] <= today
        ),
        key=lambda t: (t["date"], t.get("time", "")),
    )
    descriptions.append(f"截至本日有 {len(due)} 项待办。")
    if due:
        first = due[0]
        descriptions.append(
            f"请先核对“{first['title']}”（{first['date']}，{first['assignee']}）。"
        )
    evidence.append(cite_records("tasks", "到期且待执行的工单", due, f"{len(due)} 项"))
    return rid, f"复核{resident['name']}的照护计划", "".join(descriptions), evidence


def care_suggestion(state, payload, today):
    resident = get_resident(state, payload)
    if resident["status"] != "在住":
        raise ValueError("照护建议仅适用于在住长者")
    return draft(state, resident, today, cite_records)


def stock_suggestion(state, today):
    day = parse_day(today)
    this_start = (day - timedelta(days=6)).isoformat()
    previous_start = (day - timedelta(days=13)).isoformat()
    evidence, recommendations, alerts, trends = [], [], [], []
    for item in state["inventory"]:
        recent, earlier = [], []
        for entry in state["transactions"]:
            if entry["itemId"] != item["id"] or entry["type"] != "出库":
                continue
            if this_start <= entry["date"] <= today:
                recent.append(entry)
            elif previous_start <= entry["date"] < this_start:
                earlier.append(entry)
        current = sum(e["quantity"] for e in recent)
        previous = sum(e["quantity"] for e in earlier)
        unit, name = item["unit"], item["name"]
        change = current - previous
        trends.append((abs(change), f"{name}上期 {previous}、本期 {current} {unit}"))
        evidence.append(
            cite_records(
                "transactions",
                f"{name} · 两期出库",
                earlier + recent,
                f"前7天 {previous} {unit}，近7天 {current} {unit}，变化 {change:+d} {unit}",
            )
        )
        target = max(item["minimum"], current)
        need = max(0, target - item["quantity"])
        if need:
            recommendations.append(f"{name} {need} {unit}")
            evidence.append(
                cite_records(
                    "inventory",
                    f"{name} · 建议补量",
                    [item],
                    f"库存 {item['quantity']}，下限 {item['minimum']}，目标 {target}，缺口 {need} {unit}",
                )
            )
        if len(earlier) >= 3:
            threshold = 3 * median(e["quantity"] for e in earlier)
            flagged = [e for e in recent if e["quantity"] >= threshold]
            if flagged:
                alerts.append(f"{name} {len(flagged)} 笔")
                evidence.append(
                    cite_records(
                        "transactions",
                        f"{name} · 大额领用",
                        flagged,
                        f"前7天单笔中位数的3倍为 {threshold:g} {unit}；本期达到该值的流水共 {len(flagged)} 笔",
                    )
                )
    top = max(trends, key=lambda t: t[0])[1] if trends else "无物资记录"
    refill = "、".join(recommendations) if recommendations else "当前库存达到计划目标"
    alert = "、".join(alerts) if alerts else "未发现满足筛查条件的流水"
    detail = f"近7天与前7天相比，{top}。预计覆盖下周用量，建议补量：{refill}。大额领用：{alert}。"
    return "", "复核物资消耗与补货计划", detail, evidence


def finance_suggestion(state, today):
    debt = [b for b in state["bills"] if b["balance"] > 0]
    overdue = [b for b in debt if b["endDate"] < today]
    due_amount = sum((Decimal(str(b["balance"])) for b in debt), Decimal(0))
    late_amount = sum((Decimal(str(b["balance"])) for b in overdue), Decimal(0))
    evidence = [
        cite_records("bills", "待缴账单", debt, f"{len(debt)} 笔，¥{due_amount:.2f}"),
        cite_records(
            "bills",
            "服务期结束仍有余额",
            overdue,
            f"{len(overdue)} 笔，¥{late_amount:.2f}",
        ),
    ]
    flagged = []
    for bill in state["bills"]:
        amount, paid, balance = (
            Decimal(str(bill[k])) for k in ("amount", "paid", "balance")
        )
        reasons = []
        if bill.get("kind") == "trial":
            expected = Decimal(str(bill["trialPrice"]))
        else:
            bed_rate, care_rate, package = (
                Decimal(str(bill[k])) for k in ("bedFee", "careFee", "packageFee")
            )
            expected = (
                Decimal(str(bill.get("bedTotal", bed_rate * bill["serviceDays"])))
                + Decimal(
                    str(
                        bill.get(
                            "careTotal",
                            care_rate * (bill["serviceDays"] - bill["leaveDays"]),
                        )
                    )
                )
                + package
            )
            default_rate = CARE_RATES.get(bill["careLevel"])
            if default_rate is not None and care_rate != default_rate:
                reasons.append(
                    f"护理日价 ¥{care_rate:.2f}，示例等级标准 ¥{default_rate:.2f}"
                )
        if expected != amount or balance + paid != amount:
            reasons.append("计费拆分或核销余额与应收不符")
        if reasons:
            flagged.append(bill)
            evidence.append(
                cite_records(
                    "bills", f"{bill['month']} · 收费待核", [bill], "；".join(reasons)
                )
            )
    late_refs = "、".join(b["id"] for b in overdue[:3]) or "无"
    anomaly_refs = "、".join(b["id"] for b in flagged[:3]) or "无"
    detail = (
        f"待缴 {len(debt)} 笔 ¥{due_amount:.2f}，其中服务期结束仍欠缴 {len(overdue)} 笔 ¥{late_amount:.2f}"
        f"（账单：{late_refs}）。按计费拆分、核销余额及护理等级示例日价筛查，"
        f"{len(flagged)} 笔需复核（账单：{anomaly_refs}）。请核对签约单价与收款凭证。"
    )
    return "", "复核欠费及收费异常", detail, evidence


def generate_suggestion(state, payload, today):
    category = payload.get("category")
    if category == "日常照护":
        result = care_suggestion(state, payload, today)
    elif category == "物资管控":
        result = stock_suggestion(state, today)
    elif category == "运营分析":
        result = finance_suggestion(state, today)
    else:
        raise ValueError("请选择有效的建议类别")
    resident_id, title, detail, evidence = result
    state["suggestions"].insert(
        0,
        dict(
            id=new_id("suggest"),
            category=category,
            title=title,
            detail=detail,
            evidence=evidence,
            ruleVersion=1,
            residentId=resident_id,
            date=today,
            status="待审核",
            reviewNote="",
        ),
    )
    return f"生成{category}规则建议，等待人工审核"


def review_suggestion(state, payload, today):
    suggestion = lookup(state, "suggestions", payload.get("id"), "建议")
    if suggestion["status"] != "待审核":
        raise ValueError("建议已经完成审核")
    decision = payload.get("decision")
    if decision not in ("采纳", "驳回"):
        raise ValueError("请选择采纳或驳回")
    note = text_field(payload, "note", "审核意见", 500)
    suggestion.update(status="已" + decision, reviewNote=note, reviewedAt=today)
    return f"已{decision}「{suggestion['title']}」建议，审核意见已记录"
