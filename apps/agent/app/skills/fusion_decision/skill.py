from __future__ import annotations

from datetime import datetime

from app.harness.engine import Harness
from app.memory.bed_context import BedMemoryStore
from app.models.schemas import FusionRequest, FusionResult, RiskLevel


class FusionDecisionSkill:
    """异构多源感知信号融合决策。"""

    name = "fusion_decision"

    def __init__(self, harness: Harness, memory: BedMemoryStore) -> None:
        self.harness = harness
        self.memory = memory

    def run(self, req: FusionRequest) -> FusionResult:
        policy = self.harness.policy.data.get("fusion", {})
        sources = policy.get("sources", {})
        window = policy.get("time_window_seconds", 8)
        high_th = float(policy.get("high_risk_threshold", 0.78))
        review_th = float(policy.get("review_threshold", 0.45))

        # 时序校验：仅窗口内事件参与融合
        now = datetime.utcnow()
        valid = []
        for e in req.events:
            age = abs((now - e.ts.replace(tzinfo=None)).total_seconds()) if e.ts.tzinfo is None else abs((datetime.utcnow() - e.ts.replace(tzinfo=None)).total_seconds())
            if age <= window * 2:
                valid.append(e)

        night = req.night_mode
        if night is None:
            hour = datetime.utcnow().hour
            nb = policy.get("night_boost", {})
            start, end = nb.get("hours", [22, 6])
            night = hour >= start or hour < end if nb.get("enabled") else False

        weighted = 0.0
        weight_sum = 0.0
        reasons: list[str] = []
        for e in valid:
            cfg = sources.get(e.source.value, {"weight": 0.2, "min_confidence": 0.5})
            w = float(cfg.get("weight", 0.2))
            if night:
                if e.source.value == "acoustic_aed":
                    w += float(policy.get("night_boost", {}).get("acoustic_weight_boost", 0))
                if e.source.value == "mmwave_60g":
                    w += float(policy.get("night_boost", {}).get("mmwave_weight_boost", 0))
            if e.confidence < float(cfg.get("min_confidence", 0.5)):
                reasons.append(f"{e.source.value}置信不足({e.confidence:.2f})")
                continue
            weighted += w * e.confidence
            weight_sum += w
            reasons.append(f"{e.source.value}:{e.event_type}@{e.confidence:.2f}")

        fused = (weighted / weight_sum) if weight_sum else 0.0
        if fused >= high_th:
            level = RiskLevel.HIGH
        elif fused >= review_th:
            level = RiskLevel.REVIEW
        else:
            level = RiskLevel.INFO

        audit = self.harness.audit.start(
            self.name,
            "fuse",
            {"bed_id": req.bed_id, "events": len(valid), "fused": fused},
            human_review_required=level != RiskLevel.INFO,
        )

        routing = self.harness.policy.data.get("routing", {})
        channels = routing.get(level.value if level != RiskLevel.INFO else "review", {}).get("channels", ["review_queue"])
        if level == RiskLevel.INFO:
            channels = ["review_queue"] if fused >= review_th * 0.8 else []

        # 通过 MCP 推送（高危也只是排队，终审由人工）
        if level in (RiskLevel.HIGH, RiskLevel.REVIEW):
            self.harness.call_tool(
                "alert.push",
                {
                    "title": f"融合告警-{level.value}",
                    "risk_level": level.value,
                    "bed_id": req.bed_id,
                    "elder_id": req.elder_id,
                    "message": "; ".join(reasons),
                    "channels": channels,
                },
                audit,
            )
            self.memory.append_alert(
                req.bed_id,
                {"level": level.value, "confidence": fused, "reasons": reasons, "audit_id": audit.id},
            )

        audit.decision = {"risk_level": level.value, "fused_confidence": fused, "channels": channels}
        self.harness.audit.write(audit)

        return FusionResult(
            bed_id=req.bed_id,
            elder_id=req.elder_id,
            risk_level=level,
            fused_confidence=round(fused, 4),
            reasons=reasons,
            requires_human_review=level != RiskLevel.INFO,
            recommended_channels=channels,
            audit_id=audit.id,
        )
