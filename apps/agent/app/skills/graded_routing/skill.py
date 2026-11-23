from __future__ import annotations

from app.harness.engine import Harness
from app.models.schemas import RiskLevel


class GradedRoutingSkill:
    """分级推送路由：高危直达护工+护士长，低置信入复核队列。"""

    name = "graded_routing"

    def __init__(self, harness: Harness) -> None:
        self.harness = harness

    def route(self, risk_level: RiskLevel | str, title: str, bed_id: str, elder_id: str | None = None, message: str = "") -> dict:
        level = risk_level.value if isinstance(risk_level, RiskLevel) else risk_level
        routing = self.harness.policy.data.get("routing", {})
        channels = routing.get(level, {}).get("channels", ["review_queue"])
        if level == "info":
            channels = ["review_queue"]

        audit = self.harness.audit.start(
            self.name,
            "route",
            {"level": level, "bed_id": bed_id, "channels": channels},
            human_review_required=level == "high",
        )
        pushed = self.harness.call_tool(
            "alert.push",
            {
                "title": title,
                "risk_level": level,
                "bed_id": bed_id,
                "elder_id": elder_id,
                "message": message,
                "channels": channels,
            },
            audit,
        )
        for ch in channels:
            if ch == "wecom" or ch in ("caregiver", "head_nurse"):
                self.harness.call_tool(
                    "wecom.send",
                    {"content": f"[{level}] {title} @床位{bed_id} {message}", "to": ch, "level": level},
                    audit,
                )
        audit.decision = {"alert_id": pushed.get("id"), "channels": channels}
        self.harness.audit.write(audit)
        return {"alert": pushed, "channels": channels, "audit_id": audit.id}
