from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

_VITALS: dict[str, list[dict[str, Any]]] = {}
_STATUS_DRAFTS: list[dict[str, Any]] = []


def vitals_recent(elder_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """读取近期生命体征结构化数据。"""
    return _VITALS.get(elder_id, [])[-limit:]


def ingest_vitals(elder_id: str, vitals: list[dict[str, Any]]) -> dict[str, Any]:
    bucket = _VITALS.setdefault(elder_id, [])
    bucket.extend(vitals)
    return {"elder_id": elder_id, "count": len(bucket)}


def update_status_draft(elder_id: str, status: str, reasons: list[str]) -> dict[str, Any]:
    """健康状态自动管理草稿（禁止 Agent 终审覆盖）。"""
    item = {
        "id": f"hs_{uuid4().hex[:10]}",
        "elder_id": elder_id,
        "status": status,
        "reasons": reasons,
        "state": "draft",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _STATUS_DRAFTS.append(item)
    return item


def list_status_drafts() -> list[dict[str, Any]]:
    return list(_STATUS_DRAFTS)
