from __future__ import annotations

import random
from typing import Any

from app.harness.engine import Harness
from app.models.schemas import FeedbackRequest

_FEEDBACK: list[dict] = []
_NOISE_BANK: list[dict[str, Any]] = []


class AlertFeedbackSkill:
    """告警反馈自迭代：人工修正后自动加噪声，并视情况调阈。"""

    name = "alert_feedback"

    def __init__(self, harness: Harness) -> None:
        self.harness = harness

    def _inject_noise(self, label: str, note: str | None) -> list[dict[str, Any]]:
        """误报 → 负样本噪声；属实/漏报修正 → 正样本邻域噪声。"""
        base_conf = 0.55 if label == "false_positive" else 0.75
        scale = 0.08 if label == "false_positive" else 0.05
        injected: list[dict[str, Any]] = []
        for _ in range(3):
            sample = {
                "label": label,
                "confidence": min(1.0, max(0.0, base_conf + (random.random() - 0.5) * 2 * scale)),
                "jitter": (random.random() - 0.5) * scale,
                "note": note,
                "noise_tag": "auto_after_human_correction",
            }
            injected.append(sample)
            _NOISE_BANK.append(sample)
        if len(_NOISE_BANK) > 2000:
            del _NOISE_BANK[:-1500]
        return injected

    def run(self, req: FeedbackRequest) -> dict:
        item = req.model_dump()
        _FEEDBACK.append(item)
        noise = self._inject_noise(req.label, req.note)
        audit = self.harness.audit.start(self.name, "ingest_feedback", {**item, "noise": len(noise)})
        policy = self.harness.policy.data
        fb = policy.get("feedback", {})
        negatives = [f for f in _FEEDBACK if f.get("label") == "false_positive"]
        positives = [f for f in _FEEDBACK if f.get("label") == "true_positive"]
        tuned = False
        # 误报多 → 提高阈值（更谨慎）
        if req.label == "false_positive" and len(negatives) >= int(fb.get("min_negatives_to_tune", 3)):
            fusion = policy.get("fusion", {})
            step = float(fb.get("threshold_step", 0.02))
            high = float(fusion.get("high_risk_threshold", 0.78)) + step
            review = float(fusion.get("review_threshold", 0.45)) + step / 2
            high = min(float(fb.get("threshold_max", 0.9)), high)
            review = min(high - 0.05, max(float(fb.get("threshold_min", 0.35)), review))
            self.harness.policy.update_thresholds(high_risk_threshold=high, review_threshold=review)
            self.harness.gate = type(self.harness.gate)(self.harness.policy.data)
            tuned = True
        # 漏报纠正（属实）也可能加噪声，并略降阈值提升召回
        if req.label == "true_positive" and "漏" in (req.note or ""):
            fusion = policy.get("fusion", {})
            step = float(fb.get("threshold_step", 0.02)) / 2
            high = max(float(fb.get("threshold_min", 0.35)) + 0.1, float(fusion.get("high_risk_threshold", 0.78)) - step)
            review = max(float(fb.get("threshold_min", 0.35)), float(fusion.get("review_threshold", 0.45)) - step)
            self.harness.policy.update_thresholds(high_risk_threshold=high, review_threshold=review)
            self.harness.gate = type(self.harness.gate)(self.harness.policy.data)
            tuned = True
        audit.decision = {
            "tuned": tuned,
            "negatives": len(negatives),
            "positives": len(positives),
            "noise_injected": len(noise),
            "noise_bank": len(_NOISE_BANK),
        }
        self.harness.audit.write(audit)
        return {
            "accepted": True,
            "tuned": tuned,
            "negatives": len(negatives),
            "noise_injected": len(noise),
            "noise_bank_size": len(_NOISE_BANK),
            "audit_id": audit.id,
        }
