from __future__ import annotations

from app.harness.engine import Harness
from app.models.schemas import FeedbackRequest

_FEEDBACK: list[dict] = []


class AlertFeedbackSkill:
    """告警反馈自迭代：误报/属实回流调整融合阈值。"""

    name = "alert_feedback"

    def __init__(self, harness: Harness) -> None:
        self.harness = harness

    def run(self, req: FeedbackRequest) -> dict:
        item = req.model_dump()
        _FEEDBACK.append(item)
        audit = self.harness.audit.start(self.name, "ingest_feedback", item)
        policy = self.harness.policy.data
        fb = policy.get("feedback", {})
        negatives = [f for f in _FEEDBACK if f.get("label") == "false_positive"]
        tuned = False
        if len(negatives) >= int(fb.get("min_negatives_to_tune", 5)):
            fusion = policy.get("fusion", {})
            step = float(fb.get("threshold_step", 0.02))
            high = float(fusion.get("high_risk_threshold", 0.78)) + step
            review = float(fusion.get("review_threshold", 0.45)) + step / 2
            high = min(float(fb.get("threshold_max", 0.9)), high)
            review = min(high - 0.05, max(float(fb.get("threshold_min", 0.35)), review))
            self.harness.policy.update_thresholds(high_risk_threshold=high, review_threshold=review)
            # refresh gate policy view
            self.harness.gate = type(self.harness.gate)(self.harness.policy.data)
            tuned = True
        audit.decision = {"tuned": tuned, "negatives": len(negatives)}
        self.harness.audit.write(audit)
        return {"accepted": True, "tuned": tuned, "negatives": len(negatives), "audit_id": audit.id}
