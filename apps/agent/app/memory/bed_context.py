from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


class BedMemoryStore:
    """按床位隔离的独立上下文记忆。"""

    def __init__(self) -> None:
        self.root = Path(get_settings().memory_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bed_id: str) -> Path:
        safe = bed_id.replace("/", "_")
        return self.root / f"bed_{safe}.json"

    def load(self, bed_id: str) -> dict[str, Any]:
        path = self._path(bed_id)
        if not path.exists():
            return {
                "bed_id": bed_id,
                "elder_id": None,
                "traits": {},
                "risk_history": [],
                "alerts": [],
                "care_summaries": [],
            }
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, bed_id: str, data: dict[str, Any]) -> dict[str, Any]:
        data["bed_id"] = bed_id
        self._path(bed_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def bind_elder(self, bed_id: str, elder_id: str, traits: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = self.load(bed_id)
        ctx["elder_id"] = elder_id
        if traits:
            ctx["traits"] = {**ctx.get("traits", {}), **traits}
        return self.save(bed_id, ctx)

    def append_alert(self, bed_id: str, alert: dict[str, Any]) -> dict[str, Any]:
        ctx = self.load(bed_id)
        ctx.setdefault("alerts", []).append(alert)
        ctx["alerts"] = ctx["alerts"][-50:]
        return self.save(bed_id, ctx)

    def append_care_summary(self, bed_id: str, summary: str) -> dict[str, Any]:
        ctx = self.load(bed_id)
        ctx.setdefault("care_summaries", []).append(summary)
        ctx["care_summaries"] = ctx["care_summaries"][-30:]
        return self.save(bed_id, ctx)

    def context_prompt(self, bed_id: str) -> str:
        ctx = self.load(bed_id)
        return (
            f"床位={ctx.get('bed_id')} 老人={ctx.get('elder_id')} "
            f"特征={ctx.get('traits')} 近告警数={len(ctx.get('alerts', []))} "
            f"近照护摘要={ctx.get('care_summaries', [])[-3:]}"
        )
