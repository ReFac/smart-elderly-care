from __future__ import annotations

from app.agents.llm import DeepSeekClient
from app.harness.engine import Harness
from app.models.schemas import TypelessCommand
from app.skills.graded_routing.skill import GradedRoutingSkill
from app.skills.health_auto.skill import HealthAutoSkill
from app.skills.voice_care_record.skill import VoiceCareRecordSkill
from app.models.schemas import HealthAutoRequest, VoiceCareRequest


class VoiceTypelessSkill:
    """
    Typeless 风格全语音/自然语言入口：
    不填表单，口述意图 → 意图识别 → 路由到对应 Skill。
    """

    name = "voice_typeless"

    def __init__(
        self,
        harness: Harness,
        llm: DeepSeekClient,
        care: VoiceCareRecordSkill,
        routing: GradedRoutingSkill,
        health: HealthAutoSkill,
    ) -> None:
        self.harness = harness
        self.llm = llm
        self.care = care
        self.routing = routing
        self.health = health

    async def run(self, cmd: TypelessCommand) -> dict:
        system = "你是养老院 Typeless 语音管理 Agent。识别意图 intent=query_health|care_record|raise_alert|meeting|unknown，输出 JSON。"
        parsed = await self.llm.chat_json(system, cmd.utterance)
        intent = parsed.get("intent", "unknown")

        audit = self.harness.audit.start(
            self.name,
            "route_intent",
            {"utterance": cmd.utterance, "intent": intent},
        )
        self.harness.audit.attach_llm(audit, system + "\n" + cmd.utterance, str(parsed))

        result: dict
        if intent == "care_record" and cmd.bed_id and cmd.elder_id:
            result = (
                await self.care.run(
                    VoiceCareRequest(
                        bed_id=cmd.bed_id,
                        elder_id=cmd.elder_id,
                        transcript=cmd.utterance,
                        caregiver_id=cmd.user_id,
                    )
                )
            ).model_dump()
        elif intent == "raise_alert" and cmd.bed_id:
            result = self.routing.route("review", "语音上报异常", cmd.bed_id, cmd.elder_id, cmd.utterance)
        elif intent == "query_health" and cmd.elder_id:
            result = self.health.run(HealthAutoRequest(elder_id=cmd.elder_id, vitals=[]))
        else:
            result = {"message": "未识别到可执行意图，已记录口述", "intent": intent}

        audit.decision = {"intent": intent}
        self.harness.audit.write(audit)
        return {"intent": intent, "result": result, "audit_id": audit.id}
