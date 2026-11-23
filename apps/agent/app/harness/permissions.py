from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str
    require_human_review: bool = False


class PermissionGate:
    """Harness 权限边界：高危动作禁止 Agent 终审，禁止读原始音视频。"""

    def __init__(self, policy: dict[str, Any]) -> None:
        perms = policy.get("permissions", {})
        self.forbidden_final = set(perms.get("agent_forbidden_final_approve", []))
        self.may_read = set(perms.get("agent_may_read", []))
        self.denied = set(perms.get("agent_denied", []))

    def check_tool(self, tool_name: str, action: str | None = None) -> PermissionDecision:
        key = action or tool_name
        if key in self.denied or tool_name in self.denied:
            return PermissionDecision(False, f"工具/资源被拒绝: {key}")
        if any(d in tool_name for d in ("raw.video", "raw.audio", "waveform", "video.stream")):
            return PermissionDecision(False, "禁止访问原始音视频，仅允许结构化事件")
        if key in self.forbidden_final:
            return PermissionDecision(True, "允许执行但禁止终审，需人工复核", require_human_review=True)
        return PermissionDecision(True, "allowed")

    def finalize_guard(self, action: str) -> PermissionDecision:
        if action in self.forbidden_final:
            return PermissionDecision(
                False,
                f"高危动作 {action} 禁止 Agent 直接终审，必须人工复核",
                require_human_review=True,
            )
        return PermissionDecision(True, "ok")
