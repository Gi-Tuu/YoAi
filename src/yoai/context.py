"""YoAi Personal Context — 个人事实与偏好的持久化存储。

定位：计划书 §3.2 Personal Context 模块的最小实现。
- 零第三方依赖，只用标准库。
- JSON 原子写（os.replace），避免半截文件。
- 与 Core 的 MemoryStore 解耦：这里存"用户画像事实"，Core 存"会话历史"。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PersonalContext:
    """个人事实的键值存储。键区分大小写，值可为任意 JSON 可序列化对象。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._facts: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._facts = raw
        except (json.JSONDecodeError, OSError):
            # 损坏不静默覆盖：保留空视图，写盘时走 quarantine 逻辑。
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self._facts = {}

    def _save(self) -> None:
        """原子写：先写同目录临时文件再 replace，避免读到半截 JSON。"""
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".yoai-ctx-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    self._facts, fh, ensure_ascii=False, indent=2, sort_keys=True
                )
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def remember(self, key: str, value: Any, *, tag: str = "") -> str:
        """记住一条个人事实。key 为名称，value 为内容，tag 可选分类。"""
        now = datetime.now(timezone.utc).isoformat()
        prev = self._facts.get(key)
        self._facts[key] = {
            "value": value,
            "tag": tag,
            "created_at": prev["created_at"] if prev else now,
            "updated_at": now,
        }
        self._save()
        return f"已记住：{key}"

    def recall(self, key: str) -> Any | None:
        """按 key 取回个人事实，不存在返回 None。"""
        entry = self._facts.get(key)
        return entry["value"] if entry else None

    def forget(self, key: str) -> bool:
        """删除一条个人事实，返回是否确实删掉。"""
        existed = self._facts.pop(key, None) is not None
        if existed:
            self._save()
        return existed

    def list_all(self) -> dict[str, Any]:
        """列出全部个人事实（仅返回 value，不含元数据）。"""
        return {k: v["value"] for k, v in self._facts.items()}

    def count(self) -> int:
        """统计已记住的事实条数。"""
        return len(self._facts)
