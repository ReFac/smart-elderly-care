from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nh.agent.hooks")


def after_tool_hook(tool: str, arguments: dict[str, Any], result: Any, error: str | None) -> None:
    status = "error" if error else "ok"
    logger.info("after_tool tool=%s status=%s error=%s", tool, status, error)
