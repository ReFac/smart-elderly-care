from __future__ import annotations

import logging
from typing import Any

from app.harness.permissions import PermissionDecision

logger = logging.getLogger("nh.agent.hooks")


def before_tool_hook(tool: str, arguments: dict[str, Any], decision: PermissionDecision) -> None:
    logger.info("before_tool tool=%s allowed=%s reason=%s args_keys=%s", tool, decision.allowed, decision.reason, list(arguments.keys()))
