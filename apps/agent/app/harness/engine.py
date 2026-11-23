from __future__ import annotations

from typing import Any, Callable

from app.harness.audit import AuditLogger
from app.harness.permissions import PermissionGate
from app.harness.policy import PolicyStore
from app.hooks.after_tool import after_tool_hook
from app.hooks.before_tool import before_tool_hook
from app.hooks.human_review import queue_human_review
from app.models.schemas import AuditRecord


class Harness:
    """
    Agent 执行护栏：
    - 权限边界
    - MCP 工具调用前后 Hook
    - 全链路审计
    - 高危动作强制人工复核
    """

    def __init__(self) -> None:
        self.policy = PolicyStore()
        self.audit = AuditLogger()
        self.gate = PermissionGate(self.policy.data)
        self._tools: dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def call_tool(self, name: str, arguments: dict[str, Any], audit: AuditRecord | None = None) -> Any:
        decision = self.gate.check_tool(name, arguments.get("action"))
        before_tool_hook(name, arguments, decision)
        if not decision.allowed:
            if audit:
                self.audit.attach_tool(audit, name, arguments, allowed=False, error=decision.reason)
            raise PermissionError(decision.reason)

        try:
            result = self._tools[name](**arguments) if name in self._tools else {"error": f"unknown tool {name}"}
            after_tool_hook(name, arguments, result, None)
            if audit:
                self.audit.attach_tool(audit, name, arguments, result=result, allowed=True)
            if decision.require_human_review:
                queue_human_review(name, arguments, result)
            return result
        except Exception as exc:  # noqa: BLE001
            after_tool_hook(name, arguments, None, str(exc))
            if audit:
                self.audit.attach_tool(audit, name, arguments, error=str(exc), allowed=True)
            raise

    def guard_finalize(self, action: str) -> None:
        decision = self.gate.finalize_guard(action)
        if not decision.allowed:
            queue_human_review(action, {}, {"blocked": True, "reason": decision.reason})
            raise PermissionError(decision.reason)
