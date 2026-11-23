from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

_SNAPSHOTS: dict[str, list[dict[str, Any]]] = {}


def snapshot_read(bed_id: str, limit: int = 6) -> list[dict[str, Any]]:
    """读取床位照护事实快照（增量窗口，非全量日志）。"""
    rows = _SNAPSHOTS.get(bed_id, [])
    return rows[-limit:]


def snapshot_write_draft(
    bed_id: str,
    elder_id: str,
    facts: dict[str, Any],
    draft_text: str,
    caregiver_id: str | None = None,
) -> dict[str, Any]:
    """写入照护草稿快照，等待人工复核。"""
    item = {
        "id": f"care_{uuid4().hex[:10]}",
        "bed_id": bed_id,
        "elder_id": elder_id,
        "facts": facts,
        "draft_text": draft_text,
        "caregiver_id": caregiver_id,
        "status": "draft",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _SNAPSHOTS.setdefault(bed_id, []).append(item)
    return item
