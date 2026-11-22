"""通讯数据的持久化存储：消息历史 + 群定义。

复用 PersonalContext 的原子写 + 损坏隔离思路（JSON，标准库，零依赖）。
与 Context/Goals 分开文件，避免个人画像和聊天记录互相污染。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from yoai.chat.models import Group, Message


class ChatStore:
    """把消息与群定义落盘；同一目录两个 JSON 文件。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._messages: list[dict[str, Any]] = []
        self._groups: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._messages = raw.get("messages", [])
                    self._groups = raw.get("groups", {})
            except (json.JSONDecodeError, OSError):
                backup = self.path.with_suffix(self.path.suffix + ".corrupt")
                try:
                    self.path.replace(backup)
                except OSError:
                    pass
                self._messages, self._groups = [], {}

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".yoai-chat-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {"messages": self._messages, "groups": self._groups},
                    fh, ensure_ascii=False, indent=2,
                )
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def append_message(self, message: Message, *, max_messages: int = 2000) -> None:
        self._messages.append(message.to_dict())
        if len(self._messages) > max_messages:
            self._messages = self._messages[-max_messages:]
        self._save()

    def messages(self, *, channel: str = "") -> list[Message]:
        items = self._messages
        if channel:
            items = [m for m in items if m["recipient"] == channel or m["sender"] == channel]
        return [Message.from_dict(m) for m in items]

    def save_group(self, group: Group) -> None:
        self._groups[group.id] = group.to_dict()
        self._save()

    def groups(self) -> list[Group]:
        return [Group.from_dict(g) for g in self._groups.values()]

    def get_group(self, group_id: str) -> Group | None:
        data = self._groups.get(group_id)
        return Group.from_dict(data) if data else None

    def delete_group(self, group_id: str) -> bool:
        existed = self._groups.pop(group_id, None) is not None
        if existed:
            self._save()
        return existed

    def count(self) -> int:
        return len(self._messages)
