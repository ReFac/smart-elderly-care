"""Provider-neutral extension contracts. The installed implementation runs in-process."""

from dataclasses import dataclass, replace
from typing import Protocol


@dataclass(frozen=True)
class Specialist:
    key: str
    title: str
    grant: str
    tool: str
    collections: tuple[str, ...]
    keywords: tuple[str, ...]


SPECIALISTS = (
    Specialist(
        "care",
        "日常照护",
        "care",
        "care.review",
        ("residents", "assessments", "tasks"),
        ("照护", "护理", "交班", "交接", "签收", "接班", "工单", "评估"),
    ),
    Specialist(
        "inventory",
        "物资管控",
        "inventory",
        "stock.review",
        ("inventory", "transactions"),
        ("物资", "耗材", "库存", "补货", "领用"),
    ),
    Specialist(
        "finance",
        "运营分析",
        "finance",
        "billing.review",
        ("bills",),
        ("财务", "账单", "欠费", "经营", "营收", "结算"),
    ),
)

HANDOVER_TOOL = replace(
    next(s for s in SPECIALISTS if s.key == "care"),
    tool="handover.pending",
    collections=("handovers",),
    keywords=("签收", "待接班"),
)


class Planner(Protocol):
    """Return specialist IDs. The host validates every ID against the actor's grants."""

    def plan(self, goal: str, allowed: tuple[Specialist, ...]) -> list[str]: ...


class ToolProvider(Protocol):
    """Provider receives only its declared collections; output is a reviewable draft."""

    def collect(
        self, specialist: Specialist, records: dict, resident_id: str, day: str
    ) -> dict: ...


class TraceSink(Protocol):
    def append(
        self, agent: str, event: str, message: str, parent: str = ""
    ) -> None: ...


class LocalPlanner:
    def plan(self, goal, allowed):
        matches = [
            item for item in SPECIALISTS if any(k in goal for k in item.keywords)
        ]
        if matches and not any(item in allowed for item in matches):
            raise PermissionError("任务涉及的业务域未获授权")
        return [item.key for item in (matches or allowed) if item in allowed]


def contract(user, available):
    tools = [
        {
            "id": item.tool,
            "agent": item.key,
            "title": item.title,
            "grant": item.grant,
            "collections": list(item.collections),
            "effect": "read",
        }
        for item in available
    ]
    for tool in tools:
        if tool["agent"] == HANDOVER_TOOL.key:
            tool["optionalTools"] = [
                {
                    "id": HANDOVER_TOOL.tool,
                    "collections": list(HANDOVER_TOOL.collections),
                    "scope": "assigned_to_current_actor",
                    "effect": "read",
                    "cloudTokens": 0,
                }
            ]
    adapters = [
        {
            "id": "mcp-tools",
            "operation": "list_tools / call_tool",
            "input": ["tool", "arguments", "actorScope"],
            "output": ["structuredContent", "sourceRefs"],
        },
        {
            "id": "a2a-delegate",
            "operation": "delegate / inspect / cancel",
            "input": ["taskId", "parentRunId", "authorizedScope"],
            "output": ["taskId", "state", "artifacts"],
        },
        {
            "id": "trace-export",
            "operation": "export_events",
            "input": ["runId", "eventRange", "redactionPolicy"],
            "output": ["acknowledgedThrough"],
        },
    ]
    return {
        "version": "1.0",
        "runtime": "local-rules",
        "coordinator": "coordinator",
        "maxSteps": len(SPECIALISTS),
        "tools": tools,
        "checkpoints": ["awaiting_approval", "published", "cancelled"],
        "adapters": [
            {**item, "status": "reserved", "path": "/api/agent/adapters/" + item["id"]}
            for item in adapters
        ],
    }
