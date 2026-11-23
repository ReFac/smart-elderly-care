from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings

_OUTBOX: list[dict[str, Any]] = []


def send_message(content: str, to: str = "duty", level: str = "info") -> dict[str, Any]:
    """企微消息下发（配置 webhook 则真实推送，否则入发件箱）。"""
    settings = get_settings()
    item = {
        "to": to,
        "level": level,
        "content": content,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "delivered": False,
    }
    if settings.wecom_webhook:
        try:
            httpx.post(
                settings.wecom_webhook,
                json={"msgtype": "text", "text": {"content": f"[{level}] {content}"}},
                timeout=10,
            ).raise_for_status()
            item["delivered"] = True
        except Exception as exc:  # noqa: BLE001
            item["error"] = str(exc)
    _OUTBOX.append(item)
    return item


def list_outbox(limit: int = 50) -> list[dict[str, Any]]:
    return _OUTBOX[-limit:]
