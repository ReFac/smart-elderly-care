"""Dispatch bounded specialist work, then return evidence and a human-review checkpoint."""

from .contracts import (
    LocalPlanner,
    Planner,
    SPECIALISTS,
    Specialist,
    ToolProvider,
    TraceSink,
)
from ..operations.assistants import (
    care_suggestion,
    stock_suggestion,
    finance_suggestion,
    cite_records,
)


# Scalar-only read models. A provider can neither mutate the workspace nor read adjacent fields.
FIELDS = {
    "residents": ("id", "name", "status", "level"),
    "assessments": ("id", "residentId", "date", "level", "reviewDate"),
    "tasks": ("id", "residentId", "date", "time", "status", "title", "assignee"),
    "inventory": ("id", "name", "quantity", "minimum", "unit"),
    "transactions": ("id", "itemId", "date", "quantity", "type"),
    "bills": (
        "id",
        "month",
        "balance",
        "endDate",
        "amount",
        "paid",
        "bedFee",
        "careFee",
        "packageFee",
        "careLevel",
        "serviceDays",
        "leaveDays",
    ),
}


def scoped_records(state, spec, resident_id, member_ids=None):
    data = {}
    for collection in spec.collections:
        records = state[collection]
        key = "id" if collection == "residents" else "residentId"
        if member_ids is not None:
            if spec.key not in {"care", "finance"}:
                raise PermissionError("此工具尚未登记区域数据归属")
            records = [row for row in records if row.get(key) in member_ids]
        if resident_id and spec.key == "care":
            records = (row for row in records if row.get(key) == resident_id)
        data[collection] = [
            {k: row[k] for k in FIELDS[collection] if k in row} for row in records
        ]
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
        raise PermissionError("工具产物的专员、工具、业务类别或长者与委派不符")
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
    def collect(self, specialist, records, resident_id, day):
        if specialist.key == "care" and not resident_id:
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
                "",
                "复核范围内到期照护工单",
                f"截至 {day} 有 {len(due)} 项到期工单待执行，涉及 {count} 位长者。",
                [cite_records("tasks", "到期工单", due, f"{len(due)} 项")],
            )
        elif specialist.key == "care":
            result = care_suggestion(records, {"residentId": resident_id}, day)
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
        raise ValueError("指定长者时，请选择包含照护的协作任务")
    trace.append(
        "coordinator", "plan.created", "、".join(allowed[k].title for k in planned)
    )
    artifacts = []
    provider = tools or LocalTools()
    for key in planned:
        spec = allowed[key]
        trace.append(key, "handoff", "接收" + spec.title + "子任务", "coordinator")
        target = resident_id if spec.key == "care" else ""
        inputs = scoped_records(state, spec, target, member_ids)
        allowed_ids = {
            name: {row["id"] for row in rows} for name, rows in inputs.items()
        }
        trace.append(key, "tool.called", spec.tool, "coordinator")
        output = provider.collect(spec, inputs, target, day)
        artifact = validate_artifact(output, spec, target, allowed_ids)
        artifacts.append(artifact)
        trace.append(key, "artifact.created", artifact["title"], "coordinator")
    trace.append("coordinator", "approval.requested", "产出已保存，等待人工核对并发布")
    return artifacts
