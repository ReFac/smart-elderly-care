from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.schemas import AuditRecord, ToolCallRecord


class AuditLogger:
    """全链路审计：LLM 输入、推理判断、工具调用结果均可溯源。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.dir = Path(settings.audit_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._memory: list[dict[str, Any]] = []

    def new_id(self) -> str:
        return f"aud_{uuid.uuid4().hex[:16]}"

    def write(self, record: AuditRecord) -> AuditRecord:
        path = self.dir / f"{record.id}.json"
        payload = record.model_dump(mode="json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._memory.append(payload)
        if len(self._memory) > 500:
            self._memory = self._memory[-500:]
        return record

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        files = sorted(self.dir.glob("aud_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        out: list[dict[str, Any]] = []
        for f in files[:limit]:
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def start(
        self,
        skill: str,
        action: str,
        input_summary: dict[str, Any],
        *,
        human_review_required: bool = False,
    ) -> AuditRecord:
        return AuditRecord(
            id=self.new_id(),
            skill=skill,
            action=action,
            input_summary=input_summary,
            human_review_required=human_review_required,
            created_at=datetime.utcnow(),
        )

    def attach_llm(self, record: AuditRecord, prompt: str | None, output: str | None) -> None:
        record.llm_prompt = prompt
        record.llm_output = output

    def attach_tool(self, record: AuditRecord, tool: str, arguments: dict[str, Any], result: Any = None, error: str | None = None, allowed: bool = True) -> None:
        record.tool_calls.append(
            ToolCallRecord(tool=tool, arguments=arguments, result=result, error=error, allowed=allowed)
        )
