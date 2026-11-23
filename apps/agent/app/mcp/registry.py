from __future__ import annotations

from typing import Any, Callable

from app.harness.engine import Harness
from app.mcp.tools import alerts, care, elders, health, meeting, sensors, wecom


def build_mcp_registry(harness: Harness) -> Harness:
    """MCP 标准化工具底座：能力与 Agent 逻辑解耦，新增能力只注册工具。"""

    tools: dict[str, Callable[..., Any]] = {
        "sensor.query_events": sensors.query_events,
        "sensor.ingest_event": sensors.ingest_event,
        "alert.push": alerts.push_alert,
        "alert.list_open": alerts.list_open,
        "care.snapshot_read": care.snapshot_read,
        "care.snapshot_write_draft": care.snapshot_write_draft,
        "meeting.record_write": meeting.record_write,
        "meeting.list": meeting.list_records,
        "wecom.send": wecom.send_message,
        "elder.get_profile": elders.get_profile,
        "health.vitals_recent": health.vitals_recent,
        "health.update_status_draft": health.update_status_draft,
    }
    for name, fn in tools.items():
        harness.register_tool(name, fn)
    return harness


def mcp_manifest(harness: Harness) -> dict[str, Any]:
    return {
        "protocol": "mcp-compatible",
        "version": "2026.11",
        "tools": [
            {
                "name": name,
                "description": (fn.__doc__ or "").strip().split("\n")[0],
            }
            for name, fn in sorted(((n, harness._tools[n]) for n in harness.list_tools()), key=lambda x: x[0])
        ],
    }
