from __future__ import annotations

import math
import re
from collections import Counter

from app.agents.llm import DeepSeekClient
from app.harness.engine import Harness
from app.memory.bed_context import BedMemoryStore
from app.models.schemas import VoiceCareRequest, VoiceCareResult


def _tokenize(text: str) -> Counter[str]:
    toks = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())
    return Counter(toks)


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb + 1e-9)


class VoiceCareRecordSkill:
    """语音原生增量式照护记录：ASR 文本入，查重后仅增量合并。"""

    name = "voice_care_record"

    def __init__(self, harness: Harness, memory: BedMemoryStore, llm: DeepSeekClient) -> None:
        self.harness = harness
        self.memory = memory
        self.llm = llm

    async def run(self, req: VoiceCareRequest) -> VoiceCareResult:
        policy = self.harness.policy.data.get("voice_care", {})
        thr = float(policy.get("similarity_threshold", 0.86))
        limit = int(policy.get("max_history_snippets", 6))

        recent = self.harness.call_tool("care.snapshot_read", {"bed_id": req.bed_id, "limit": limit})
        vec = _tokenize(req.transcript)
        for row in recent:
            sim = cosine(vec, _tokenize(row.get("draft_text", "")))
            if sim >= thr:
                audit = self.harness.audit.start(
                    self.name,
                    "skip_duplicate",
                    {"bed_id": req.bed_id, "similarity": sim},
                )
                self.harness.audit.write(audit)
                return VoiceCareResult(
                    draft_id=row.get("id", ""),
                    incremental=False,
                    skipped_duplicate=True,
                    facts=row.get("facts", {}),
                    draft_text=row.get("draft_text", ""),
                    requires_human_review=True,
                    audit_id=audit.id,
                )

        ctx = self.memory.context_prompt(req.bed_id)
        system = "你是养老院照护记录 Agent。从口述提取结构化 facts，只输出 JSON。"
        user = f"上下文:{ctx}\n口述:{req.transcript}"
        parsed = await self.llm.chat_json(system, user)
        facts = parsed.get("facts") or {"raw": req.transcript}
        draft_text = parsed.get("draft_text") or req.transcript.strip()

        audit = self.harness.audit.start(
            self.name,
            "incremental_merge",
            {"bed_id": req.bed_id, "elder_id": req.elder_id},
            human_review_required=True,
        )
        self.harness.audit.attach_llm(audit, system + "\n" + user, str(parsed))

        saved = self.harness.call_tool(
            "care.snapshot_write_draft",
            {
                "bed_id": req.bed_id,
                "elder_id": req.elder_id,
                "facts": facts,
                "draft_text": draft_text,
                "caregiver_id": req.caregiver_id,
            },
            audit,
        )
        self.memory.append_care_summary(req.bed_id, draft_text[:80])
        # 禁止 Agent 终审发布
        try:
            self.harness.guard_finalize("care_record.publish")
        except PermissionError:
            pass

        audit.decision = {"draft_id": saved.get("id"), "incremental": True}
        self.harness.audit.write(audit)
        return VoiceCareResult(
            draft_id=saved["id"],
            incremental=True,
            skipped_duplicate=False,
            facts=facts,
            draft_text=draft_text,
            requires_human_review=True,
            audit_id=audit.id,
        )
