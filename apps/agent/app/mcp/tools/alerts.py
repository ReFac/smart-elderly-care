from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

_ALERTS: list[dict[str, Any]] = []


def push_alert(
    title: str,
    risk_level: str,
    bed_id: str,
    elder_id: str | None = None,
    message: str | None = None,
    channels: list[str] | None = None,
) -> dict[str, Any]:
    """推送分级告警到路由通道（不含终审）。"""
    item = {
        "id": f"al_{uuid4().hex[:10]}",
        "title": title,
        "risk_level": risk_level,
        "bed_id": bed_id,
        "elder_id": elder_id,
        "message": message,
        "channels": channels or [],
        "status": "queued",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _ALERTS.append(item)
    return item


def list_open() -> list[dict[str, Any]]:
    """列出未关闭告警。"""
    return [a for a in _ALERTS if a.get("status") != "closed"]
