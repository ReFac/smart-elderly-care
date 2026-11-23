from __future__ import annotations

import math
import re
from collections import Counter

from app.agents.llm import DeepSeekClient
from app.harness.engine import Harness
from app.models.schemas import MeetingRequest, MeetingResult


def _tok(t: str) -> Counter[str]:
    return Counter(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", t.lower()))


def _sim(a: str, b: str) -> float:
    ca, cb = _tok(a), _tok(b)
    keys = set(ca) | set(cb)
    if not keys:
        return 0.0
    dot = sum(ca[k] * cb[k] for k in keys)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb + 1e-9)


class MeetingMinutesSkill:
    """交接班/风险研判会：分段压缩摘要 + 待办提取。"""

    name = "meeting_minutes"

    def __init__(self, harness: Harness, llm: DeepSeekClient) -> None:
        self.harness = harness
        self.llm = llm

    async def run(self, req: MeetingRequest) -> MeetingResult:
        policy = self.harness.policy.data.get("meeting", {})
        merge_thr = float(policy.get("merge_similarity", 0.82))

        # 分层：先局部压缩，再全局提炼，控制 token
        compressed: list[str] = []
        for seg in req.transcript_segments:
            if len(seg) <= 120:
                compressed.append(seg)
            else:
                compressed.append(seg[:80] + "…" + seg[-40:])

        # 跨片段合并近似重复
        merged: list[str] = []
        for s in compressed:
            if any(_sim(s, m) >= merge_thr for m in merged):
                continue
            merged.append(s)

        system = "你是养老院会议纪要 Agent。输出 JSON：topics/risks/todos/conflicts/summary。"
        user = f"会议类型:{req.meeting_type}\n参会:{req.attendees}\n片段:\n" + "\n".join(merged)
        parsed = await self.llm.chat_json(system, user)

        audit = self.harness.audit.start(
            self.name,
            "summarize",
            {"segments": len(req.transcript_segments), "merged": len(merged)},
            human_review_required=True,
        )
        self.harness.audit.attach_llm(audit, system + "\n" + user, str(parsed))

        todos = parsed.get("todos") or []
        summary = {
            "topics": parsed.get("topics") or [],
            "risks": parsed.get("risks") or [],
            "todos": todos,
            "conflicts": parsed.get("conflicts") or [],
            "summary": parsed.get("summary") or "（空）",
        }
        saved = self.harness.call_tool(
            "meeting.record_write",
            {"meeting_type": req.meeting_type, "summary": summary},
            audit,
        )

        # 待办转工单：仅草稿，禁止终审
        for todo in todos:
            try:
                self.harness.guard_finalize("meeting.todo.create_order")
            except PermissionError:
                self.harness.call_tool(
                    "wecom.send",
                    {
                        "content": f"[待复核待办] {todo}",
                        "to": "head_nurse",
                        "level": "review",
                    },
                    audit,
                )

        audit.decision = {"meeting_id": saved.get("id"), "todos": len(todos)}
        self.harness.audit.write(audit)
        return MeetingResult(
            topics=summary["topics"],
            risks=summary["risks"],
            todos=todos,
            conflicts=summary["conflicts"],
            summary=summary["summary"],
            requires_human_review=True,
            audit_id=audit.id,
        )
