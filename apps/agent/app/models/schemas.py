from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    HIGH = "high"
    REVIEW = "review"
    INFO = "info"


class SensorSource(str, Enum):
    CV_POSE = "cv_pose"
    MMWAVE_60G = "mmwave_60g"
    ACOUSTIC_AED = "acoustic_aed"
    CALL_TERMINAL = "call_terminal"


class SensorEvent(BaseModel):
    source: SensorSource
    bed_id: str
    elder_id: str | None = None
    event_type: str
    confidence: float = Field(ge=0, le=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=datetime.utcnow)


class FusionRequest(BaseModel):
    bed_id: str
    elder_id: str | None = None
    events: list[SensorEvent]
    night_mode: bool | None = None


class FusionResult(BaseModel):
    bed_id: str
    elder_id: str | None
    risk_level: RiskLevel
    fused_confidence: float
    reasons: list[str]
    requires_human_review: bool
    recommended_channels: list[str]
    audit_id: str


class VoiceCareRequest(BaseModel):
    bed_id: str
    elder_id: str
    transcript: str
    caregiver_id: str | None = None
    asr_confidence: float = 0.9


class VoiceCareResult(BaseModel):
    draft_id: str
    incremental: bool
    skipped_duplicate: bool
    facts: dict[str, Any]
    draft_text: str
    requires_human_review: bool
    audit_id: str


class MeetingRequest(BaseModel):
    meeting_type: str = "handover"
    transcript_segments: list[str]
    attendees: list[str] = Field(default_factory=list)


class MeetingResult(BaseModel):
    topics: list[str]
    risks: list[str]
    todos: list[dict[str, Any]]
    conflicts: list[str]
    summary: str
    requires_human_review: bool
    audit_id: str


class FeedbackRequest(BaseModel):
    alert_id: str
    label: str  # true_positive | false_positive
    note: str | None = None


class TypelessCommand(BaseModel):
    """自然语言 / 全语音指令（Typeless 风格，无表单）。"""

    utterance: str
    bed_id: str | None = None
    elder_id: str | None = None
    user_id: str | None = None
    channel: str = "voice"


class HealthAutoRequest(BaseModel):
    elder_id: str
    vitals: list[dict[str, Any]] = Field(default_factory=list)


class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    allowed: bool = True


class AuditRecord(BaseModel):
    id: str
    skill: str
    action: str
    input_summary: dict[str, Any]
    llm_prompt: str | None = None
    llm_output: str | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    decision: dict[str, Any] = Field(default_factory=dict)
    human_review_required: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
