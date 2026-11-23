from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

_EVENTS: list[dict[str, Any]] = []


def ingest_event(
    source: str,
    bed_id: str,
    event_type: str,
    confidence: float,
    elder_id: str | None = None,
    payload: dict[str, Any] | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """写入结构化传感器事件（禁止原始音视频）。"""
    item = {
        "source": source,
        "bed_id": bed_id,
        "elder_id": elder_id,
        "event_type": event_type,
        "confidence": confidence,
        "payload": payload or {},
        "ts": ts or datetime.utcnow().isoformat() + "Z",
    }
    _EVENTS.append(item)
    if len(_EVENTS) > 2000:
        del _EVENTS[:1000]
    return item


def query_events(bed_id: str | None = None, since_seconds: int = 30) -> list[dict[str, Any]]:
    """查询结构化传感器事件。"""
    cutoff = datetime.utcnow() - timedelta(seconds=since_seconds)
    out = []
    for e in _EVENTS:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", ""))
        except Exception:
            ts = datetime.utcnow()
        if ts < cutoff:
            continue
        if bed_id and e.get("bed_id") != bed_id:
            continue
        out.append(e)
    return out
