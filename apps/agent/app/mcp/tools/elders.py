from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

_LOCAL_PROFILES: dict[str, dict[str, Any]] = {}


def get_profile(elder_id: str) -> dict[str, Any]:
    """获取老人画像：优先 Nest API，失败则本地缓存/占位。"""
    settings = get_settings()
    if settings.nest_token:
        try:
            headers = {"Authorization": f"Bearer {settings.nest_token}"}
            with httpx.Client(timeout=8) as client:
                r = client.get(f"{settings.nest_api_base}/elders/{elder_id}", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    _LOCAL_PROFILES[elder_id] = data
                    return data
        except Exception:
            pass
    return _LOCAL_PROFILES.get(
        elder_id,
        {
            "id": elder_id,
            "name": "未知老人",
            "careLevel": "unknown",
            "wanderRisk": False,
            "source": "local_placeholder",
        },
    )


def cache_profile(elder_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    _LOCAL_PROFILES[elder_id] = profile
    return profile
