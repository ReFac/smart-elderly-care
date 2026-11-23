from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.harness.engine import Harness


class AcousticAnomalySkill:
    """床头麦克风异常：转发 Nest clinical-intel（SOTA 由业务侧 URL 配置）。"""

    name = "acoustic_anomaly"

    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.settings = get_settings()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        audit = self.harness.audit.start(self.name, "ingest", payload, human_review_required=False)
        api = getattr(self.settings, "nursing_api_base", None) or "http://127.0.0.1:3000/api"
        token = payload.get("access_token") or getattr(self.settings, "service_token", "") or ""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = {
            "elderId": payload.get("elder_id") or payload.get("elderId"),
            "bedId": payload.get("bed_id") or payload.get("bedId"),
            "deviceId": payload.get("device_id") or payload.get("deviceId"),
            "hint": payload.get("hint") or payload.get("event_type"),
            "confidence": payload.get("confidence", 0.6),
            "paroxysmal": payload.get("paroxysmal"),
            "hard": payload.get("hard"),
            "audioUri": payload.get("audio_uri") or payload.get("audioUri"),
            "features": payload.get("features"),
        }
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.post(f"{api.rstrip('/')}/clinical/events/ingest", json=body, headers=headers)
                data = r.json() if r.content else {"status_code": r.status_code}
        except Exception as e:  # noqa: BLE001
            data = {"error": str(e), "reserved": True, "docs": "docs/clinical-intel-sota.md"}
        audit.decision = {"forwarded": True, "pathological": (data or {}).get("classification", {}).get("pathological")}
        self.harness.audit.write(audit)
        return {"audit_id": audit.id, "result": data}
