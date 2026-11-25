"""桌面端用户配置（YoAi 侧，纯标准库）。

持久化位置：<data_dir>/config.json（如 dist/output/config.json）
优先级：用户 UI 设置 > 环境变量 YOAI_PERMISSION_MODE > 默认 smart。
切换会话时 SessionManager 用 agent_kwargs 重建 agent，因此档位必须在
构造参数里生效，不能只改当前 agent 的 policy 对象。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_VALID_LEVELS = {"full", "smart", "manual"}
_LOCK = threading.RLock()   # save() 内调用 load() 会重入，必须用可重入锁


class UserConfig:
    def __init__(self, data_dir: Path | str) -> None:
        self.path = Path(data_dir) / "config.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with _LOCK:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                return {}

    def save(self, patch: dict[str, Any]) -> dict[str, Any]:
        with _LOCK:
            data = self.load()
            data.update(patch)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.path)
            return data

    def permission_level(self) -> str:
        """返回用户显式设置的档位；未设置返回空串（让环境变量/默认值生效）。"""
        level = str(self.load().get("permission_level", "")).strip().lower()
        return level if level in _VALID_LEVELS else ""
