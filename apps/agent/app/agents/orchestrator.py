from __future__ import annotations

from app.agents.llm import DeepSeekClient
from app.harness.engine import Harness
from app.mcp.registry import build_mcp_registry, mcp_manifest
from app.memory.bed_context import BedMemoryStore
from app.skills.alert_feedback.skill import AlertFeedbackSkill
from app.skills.fusion_decision.skill import FusionDecisionSkill
from app.skills.graded_routing.skill import GradedRoutingSkill
from app.skills.health_auto.skill import HealthAutoSkill
from app.skills.meeting_minutes.skill import MeetingMinutesSkill
from app.skills.voice_care_record.skill import VoiceCareRecordSkill
from app.skills.voice_typeless.skill import VoiceTypelessSkill
from app.skills.acoustic_anomaly.skill import AcousticAnomalySkill


class AgentOrchestrator:
    """统一编排：Harness + MCP + Skills。"""

    def __init__(self) -> None:
        self.harness = Harness()
        build_mcp_registry(self.harness)
        self.llm = DeepSeekClient()
        self.memory = BedMemoryStore()
        self.fusion = FusionDecisionSkill(self.harness, self.memory)
        self.care = VoiceCareRecordSkill(self.harness, self.memory, self.llm)
        self.meeting = MeetingMinutesSkill(self.harness, self.llm)
        self.feedback = AlertFeedbackSkill(self.harness)
        self.routing = GradedRoutingSkill(self.harness)
        self.health = HealthAutoSkill(self.harness)
        self.typeless = VoiceTypelessSkill(self.harness, self.llm, self.care, self.routing, self.health)
        self.acoustic = AcousticAnomalySkill(self.harness)

    def manifest(self) -> dict:
        return {
            "runtime": "nh-agent",
            "year_tag": "2026-11",
            "capabilities": [
                "fusion_decision",
                "voice_care_record",
                "meeting_minutes",
                "harness_audit",
                "mcp_tools",
                "alert_feedback_loop",
                "bed_memory",
                "graded_routing",
                "voice_typeless",
                "health_auto",
                "acoustic_anomaly",
            ],
            "mcp": mcp_manifest(self.harness),
            "policy_version": self.harness.policy.data.get("version"),
            "docs": ["docs/clinical-intel-sota.md"],
        }
