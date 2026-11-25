"""桌面端用户配置（YoAi 侧，纯标准库）。

持久化位置：<data_dir>/config.json（如 dist/output/config.json）

权限档位**按会话独立**：
    {"permission_levels": {"<session_id>": "smart", ...},   # 每会话档位
     "permission_default": "smart"}                          # 新会话初始档位

优先级：会话自己设置 > 全局默认（用户设的）> 环境变量 > smart。
切会话时 runtime 从本文件读该会话档位，应用到目标 agent。
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

    @staticmethod
    def _valid(level: Any) -> str:
        value = str(level or "").strip().lower()
        return value if value in _VALID_LEVELS else ""

    def default_level(self) -> str:
        """新会话的初始档位（用户显式设过才有值；空串=让环境/默认生效）。"""
        data = self.load()
        return self._valid(data.get("permission_default")) or self._valid(
            data.get("permission_level"))   # 兼容旧版全局单值配置

    def permission_level(self, session_id: str = "") -> str:
        """指定会话的档位；未单独设置则回落到全局默认。"""
        data = self.load()
        levels = data.get("permission_levels")
        if session_id and isinstance(levels, dict):
            found = self._valid(levels.get(session_id))
            if found:
                return found
        return self.default_level()

    def _write(self, data: dict[str, Any]) -> None:
        """已持锁时的写入（避免 save 再 load 造成读改写竞争）。"""
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def set_permission(self, session_id: str, level: str) -> bool:
        """设置某会话档位（不传 session_id 则设全局默认）。"""
        level = self._valid(level)
        if not level:
            return False
        with _LOCK:
            data = self.load()
            if session_id:
                levels = data.get("permission_levels")
                if not isinstance(levels, dict):
                    levels = {}
                levels[session_id] = level
                data["permission_levels"] = levels
            else:
                data["permission_default"] = level
            self._write(data)
        return True

    def apply_default_to(self, session_id: str, level: str) -> None:
        """新会话首次使用时，把当前生效档位固化为它自己的初始值。"""
        if session_id and level and not self.permission_level(session_id):
            self.set_permission(session_id, level)
