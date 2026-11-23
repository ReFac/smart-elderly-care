from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings

_QUEUE: list[dict[str, Any]] = []


def queue_human_review(action: str, arguments: dict[str, Any], result: Any) -> dict[str, Any]:
    item = {
        "id": f"rev_{uuid.uuid4().hex[:12]}",
        "action": action,
        "arguments": arguments,
        "result": result,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _QUEUE.append(item)
    settings = get_settings()
    path = Path(settings.audit_dir) / "human_review_queue.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def list_reviews(status: str | None = "pending") -> list[dict[str, Any]]:
    if status is None:
        return list(_QUEUE)
    return [x for x in _QUEUE if x.get("status") == status]


def resolve_review(review_id: str, decision: str, note: str | None = None) -> dict[str, Any]:
    for item in _QUEUE:
        if item["id"] == review_id:
            item["status"] = decision
            item["note"] = note
            item["resolved_at"] = datetime.utcnow().isoformat() + "Z"
            return item
    raise KeyError(review_id)
