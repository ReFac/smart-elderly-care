from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


class PolicyStore:
    """可热更新策略：融合阈值、路由、语音查重等，无需改代码。"""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or get_settings().policy_path)
        self._lock = threading.RLock()
        self._mtime: float = 0
        self._data: dict[str, Any] = {}
        self.reload(force=True)

    def reload(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                self._data = {}
                return self._data
            mtime = self.path.stat().st_mtime
            if force or mtime != self._mtime:
                self._data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
                self._mtime = mtime
            return self._data

    @property
    def data(self) -> dict[str, Any]:
        return self.reload()

    def update_thresholds(self, **kwargs: float) -> dict[str, Any]:
        with self._lock:
            data = self.reload(force=True)
            fusion = data.setdefault("fusion", {})
            for k, v in kwargs.items():
                fusion[k] = v
            self.path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            self._mtime = self.path.stat().st_mtime
            self._data = data
            return data
