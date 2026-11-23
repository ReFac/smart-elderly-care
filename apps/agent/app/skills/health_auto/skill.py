from __future__ import annotations

from app.harness.engine import Harness
from app.models.schemas import HealthAutoRequest


class HealthAutoSkill:
    """老人健康状态自动管理：体征规则草稿，禁止 Agent 终审覆盖。"""

    name = "health_auto"

    def __init__(self, harness: Harness) -> None:
        self.harness = harness

    def run(self, req: HealthAutoRequest) -> dict:
        if req.vitals:
            self.harness.call_tool("health.vitals_recent", {"elder_id": req.elder_id})  # warm path
            from app.mcp.tools.health import ingest_vitals

            ingest_vitals(req.elder_id, req.vitals)

        vitals = self.harness.call_tool("health.vitals_recent", {"elder_id": req.elder_id, "limit": 50})
        reasons: list[str] = []
        status = "stable"
        for v in vitals[-10:]:
            sys = v.get("systolic")
            glu = v.get("glucose")
            temp = v.get("temperature")
            spo2 = v.get("spo2")
            if sys and sys >= 160:
                status = "attention"
                reasons.append(f"收缩压偏高 {sys}")
            if glu and glu >= 11:
                status = "attention"
                reasons.append(f"血糖偏高 {glu}")
            if temp and temp >= 38:
                status = "urgent"
                reasons.append(f"发热 {temp}")
            if spo2 and spo2 < 92:
                status = "urgent"
                reasons.append(f"血氧偏低 {spo2}")

        audit = self.harness.audit.start(
            self.name,
            "auto_status",
            {"elder_id": req.elder_id, "vitals": len(vitals)},
            human_review_required=True,
        )
        draft = self.harness.call_tool(
            "health.update_status_draft",
            {"elder_id": req.elder_id, "status": status, "reasons": reasons or ["未见明显异常"]},
            audit,
        )
        try:
            self.harness.guard_finalize("health.status.overwrite")
        except PermissionError:
            pass

        if status != "stable" and self.harness.policy.data.get("health_auto", {}).get("alert_on_abnormal", True):
            self.harness.call_tool(
                "alert.push",
                {
                    "title": f"健康状态自动预警:{status}",
                    "risk_level": "high" if status == "urgent" else "review",
                    "bed_id": f"elder:{req.elder_id}",
                    "elder_id": req.elder_id,
                    "message": "; ".join(reasons),
                    "channels": ["head_nurse", "review_queue"],
                },
                audit,
            )

        audit.decision = {"status": status, "draft_id": draft.get("id")}
        self.harness.audit.write(audit)
        return {"status": status, "reasons": reasons, "draft": draft, "audit_id": audit.id}
