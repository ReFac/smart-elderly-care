"""Dispatch bounded specialist work, then return evidence and a human-review checkpoint."""

from dataclasses import replace
from . import react

from .contracts import (
    CARE_PLAN_TOOL,
    HANDOVER_TOOL,
    REVENUE_TOOL,
    LocalPlanner,
    Planner,
    SPECIALISTS,
    Specialist,
    ToolProvider,
    TraceSink,
)
from .revenue import receipts
from ..operations.care_draft import assessment_facts, plan_facts
from ..operations.assistants import (
    care_suggestion,
    care_review,
    finance_line_total,
    stock_suggestion,
    finance_suggestion,
    cite_records,
)


# Scalar-only read models. A provider can neither mutate the workspace nor read adjacent fields.
FIELDS = {
    "residents": ("id", "name", "status", "level"),
    "assessments": ("id", "residentId", "date", "level", "reviewDate"),
    "plans": (
        "id",
        "residentId",
        "assessmentId",
        "date",
        "status",
        "assignee",
        "reviewDate",
    ),
    "tasks": ("id", "residentId", "date", "time", "status", "title", "assignee"),
    "handovers": ("id", "residentId", "date"),
    "payments": ("id", "date", "method", "amount"),
    "depositEntries": ("id", "date", "amount"),
    "inventory": ("id", "name", "quantity", "minimum", "unit"),
    "transactions": ("id", "itemId", "date", "quantity", "type"),
    "bills": (
        "id",
        "month",
        "kind",
        "trialPrice",
        "depositMonths",
        "depositUnitPrice",
        "balance",
        "endDate",
        "amount",
        "paid",
        "bedFee",
        "careFee",
        "packageFee",
        "careLevel",
        "bedTotal",
        "careTotal",
        "serviceDays",
        "leaveDays",
    ),
}


def scoped_records(state, spec, resident_id, member_ids=None, *, actor_id=None):
    if spec.tool == CARE_PLAN_TOOL.tool and not resident_id:
        raise ValueError("请先选择一位长辈再生成个体照护计划")
    archived = {
        r["id"]
        for r in state.get("residents", ())
        if r.get("status") in ("未入住", "已退住", "归档到期")
    }
    data = {}
    for collection in spec.collections:
        records = state[collection]
        if collection == "handovers":
            records = [
                row
                for row in records
                if actor_id
                and row.get("assigneeId") == actor_id
                and row.get("status") == "待签收"
            ]
        key = "id" if collection == "residents" else "residentId"
        if archived:
            records = [row for row in records if row.get(key) not in archived]
        if member_ids is not None:
            if spec.key not in {"care", "finance"}:
                raise PermissionError("此工具尚未登记区域数据归属")
            records = [row for row in records if row.get(key) in member_ids]
        if resident_id and spec.key == "care":
            records = (row for row in records if row.get(key) == resident_id)
        fields = (
            ("id", "date", "amount", "kind")
            if spec.tool == REVENUE_TOOL.tool and collection == "bills"
            else FIELDS[collection]
        )
        data[collection] = []
        for row in records:
            item = {k: row[k] for k in fields if k in row}
            if collection == "bills" and spec.tool != REVENUE_TOOL.tool and row.get("lineItems"):
                item["lineTotal"] = finance_line_total(row)
            if spec.tool == CARE_PLAN_TOOL.tool:
                if collection == "assessments":
                    item.update(assessment_facts(row))
                elif collection == "plans":
                    item.update(plan_facts(row))
            data[collection].append(item)
    return data


def validate_artifact(artifact, spec, resident_id, allowed_ids):
    """Accept only registered identities and citations from the tool's original view."""
    identity = {
        "agent": spec.key,
        "tool": spec.tool,
        "category": spec.title,
        "residentId": resident_id,
    }
    if not isinstance(artifact, dict) or set(artifact) != {
        *identity,
        "title",
        "detail",
        "evidence",
    }:
        raise ValueError("工具产物字段无效")
    if any(artifact[key] != value for key, value in identity.items()):
        raise PermissionError("工具产物的专员、工具、业务类别或长辈与委派不符")
    if not all(
        isinstance(artifact[k], str) and artifact[k].strip()
        for k in ("title", "detail")
    ):
        raise ValueError("工具产物需要标题和说明")
    if not isinstance(artifact["evidence"], list):
        raise ValueError("工具产物的证据格式无效")
    evidence = []
    for ref in artifact["evidence"]:
        if not isinstance(ref, dict) or set(ref) != {
            "source",
            "recordIds",
            "label",
            "value",
        }:
            raise ValueError("证据字段无效")
        source = ref["source"]
        if not isinstance(source, str) or source not in allowed_ids:
            raise PermissionError("证据来源超出本次工具的读取范围")
        ids = ref["recordIds"]
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError("证据记录编号格式无效")
        if any(i not in allowed_ids[source] for i in ids):
            raise PermissionError("证据记录超出本次工具的读取范围")
        if not all(isinstance(ref[k], str) for k in ("label", "value")):
            raise ValueError("证据标签和计算值必须为文本")
        # Copy provider-owned containers before the next specialist is called.
        evidence.append({**ref, "recordIds": list(ids)})
    return {
        **identity,
        "title": artifact["title"],
        "detail": artifact["detail"],
        "evidence": evidence,
    }


class LocalTools:
    def __init__(self, goal=""):
        self.goal = goal

    def collect(self, specialist, records, resident_id, day):
        if specialist.tool == HANDOVER_TOOL.tool:
            pending = records["handovers"]
            # Entries are appended in creation order. Cap citations in the saved brief.
            result = (
                resident_id,
                "核对发起人待签收的交班",
                f"当前范围内有 {len(pending)} 条交班等待发起人签收。",
                [
                    cite_records(
                        "handovers",
                        "待签收交班（最近 10 条）",
                        pending[-10:][::-1],
                        f"共 {len(pending)} 条",
                    )
                ],
            )
        elif specialist.tool == REVENUE_TOOL.tool:
            result = receipts(records, self.goal, day)
        elif specialist.tool == CARE_PLAN_TOOL.tool:
            result = care_suggestion(records, {"residentId": resident_id}, day)
        elif specialist.key == "care" and resident_id:
            result = care_review(records, {"residentId": resident_id}, day)
        elif specialist.key == "care":
            due = sorted(
                (
                    r
                    for r in records["tasks"]
                    if r["status"] == "待执行" and r["date"] <= day
                ),
                key=lambda r: (r["date"], r["time"]),
            )
            count = len({r["residentId"] for r in due})
            result = (
                resident_id,
                "复核范围内到期照护工单",
                f"截至 {day} 有 {len(due)} 项到期工单待执行，涉及 {count} 位长辈。",
                [cite_records("tasks", "到期工单", due, f"{len(due)} 项")],
            )
        elif specialist.key == "inventory":
            result = stock_suggestion(records, day)
        else:
            result = finance_suggestion(records, day)
        person, title, detail, evidence = result
        return dict(
            agent=specialist.key,
            tool=specialist.tool,
            category=specialist.title,
            residentId=person,
            title=title,
            detail=detail,
            evidence=evidence,
        )


def execute(
    goal: str,
    available: tuple[Specialist, ...],
    scope: str,
    state: dict,
    resident_id: str,
    day: str,
    trace: TraceSink,
    planner: Planner | None = None,
    tools: ToolProvider | None = None,
    provider_plan: dict | None = None,
    member_ids: frozenset | None = None,
    actor_id: str | None = None,
):
    allowed = {s.key: s for s in available}
    planned = (
        (planner or LocalPlanner()).plan(goal, available)
        if scope == "auto"
        else [scope]
    )
    if provider_plan and provider_plan["mode"] == "deepseek":
        planned = provider_plan["specialistIds"]
    if (
        not planned
        or len(planned) > len(SPECIALISTS)
        or len(set(planned)) != len(planned)
    ):
        raise ValueError("协作计划为空或超过运行步数")
    if any(key not in allowed for key in planned):
        raise PermissionError("协作计划使用了未授权的工具")
    if resident_id and "care" not in planned:
        raise ValueError("指定长辈时，请选择包含照护的协作任务")
    trace.append(
        "coordinator", "plan.created", "、".join(allowed[k].title for k in planned)
    )
    artifacts = []
    provider = tools or LocalTools(goal)
    for key in planned:
        spec = allowed[key]
        if key == HANDOVER_TOOL.key and any(
            word in goal for word in HANDOVER_TOOL.keywords
        ):
            spec = HANDOVER_TOOL
        elif key == CARE_PLAN_TOOL.key and any(
            word in goal for word in CARE_PLAN_TOOL.keywords
        ):
            spec = CARE_PLAN_TOOL
        elif key == REVENUE_TOOL.key and any(
            word in goal for word in REVENUE_TOOL.keywords
        ):
            spec = (
                REVENUE_TOOL
                if any(w in goal for w in ("营收", "收入"))
                else replace(REVENUE_TOOL, collections=("depositEntries", "payments"))
            )
        trace.append(key, "handoff", "接收" + spec.title + "子任务", "coordinator")
        target = resident_id if spec.key == "care" else ""
        inputs = scoped_records(state, spec, target, member_ids, actor_id=actor_id)
        allowed_ids = {
            name: {row["id"] for row in rows} for name, rows in inputs.items()
        }
        trace.append(key, "tool.called", spec.tool, "coordinator")
        action = react.Action(
            spec.tool, spec.title, lambda: provider.collect(spec, inputs, target, day)
        )
        output = react.observe((action,), [spec.tool])[spec.tool]
        artifact = validate_artifact(output, spec, target, allowed_ids)
        trace.append(key, "tool.observed", "已核对资料引用范围", "coordinator")
        artifacts.append(artifact)
        trace.append(key, "artifact.created", artifact["title"], "coordinator")
    trace.append("coordinator", "approval.requested", "产出已保存，等待人工核对并发布")
    return artifacts
