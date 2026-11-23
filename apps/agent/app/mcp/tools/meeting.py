from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

_MEETINGS: list[dict[str, Any]] = []


def record_write(meeting_type: str, summary: dict[str, Any]) -> dict[str, Any]:
    """保存会议纪要结构化结果。"""
    item = {
        "id": f"mt_{uuid4().hex[:10]}",
        "meeting_type": meeting_type,
        "summary": summary,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _MEETINGS.append(item)
    return item


def list_records(limit: int = 20) -> list[dict[str, Any]]:
    """列出最近会议记录。"""
    return _MEETINGS[-limit:]
