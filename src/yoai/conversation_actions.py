"""会话消息动作覆盖层（YoAi 侧，内核零改动）。

撤回/编辑不物理删除 Core 历史：Core 的 MemoryStore 只有 append/history/clear，
没有单点删除。这里把「隐藏区间」记在独立 JSONL 里，包装 memory.history() 时
过滤这些区间；原始记录仍留在 SQLite，可审计、可回溯。

语义：
- retract：隐藏 [hide_from, hide_until)，通常是一条用户消息 + 紧随的助手回答；
- edit：隐藏 [hide_from, hide_until)，新提问由新任务追加到末尾（hide_until 是当前长度）；
- regenerate：只隐藏上一轮助手回答，重新生成的回答追加到末尾。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


class ConversationActions:
    """按会话保存隐藏区间；纯数据层，线程安全，损坏不致命。"""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "conversation_actions.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if isinstance(record, dict):
                    self._records.append(record)
        except (OSError, ValueError):
            # 损坏不致命：备份后从空开始，避免 runtime 起不来
            try:
                self.path.replace(self.path.with_suffix(".jsonl.corrupt"))
            except OSError:
                pass
            self._records = []

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".conv-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for record in self._records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, *, session_id: str, kind: str, hide_from: int,
            hide_until: int, text_hash: str = "", note: str = "") -> dict[str, Any]:
        record = {
            "id": uuid.uuid4().hex[:12],
            "session_id": str(session_id),
            "kind": str(kind),
            "hide_from": int(hide_from),
            "hide_until": int(hide_until),
            "text_hash": str(text_hash),
            "note": str(note),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._records.append(record)
            self._save()
        return record

    def hidden_indices(self, session_id: str, total: int) -> set[int]:
        hidden: set[int] = set()
        with self._lock:
            records: Iterable[dict[str, Any]] = self._records
            for record in records:
                if record.get("session_id") != session_id:
                    continue
                start = max(0, int(record.get("hide_from", -1)))
                end = min(total, int(record.get("hide_until", -1)))
                if 0 <= start < end:
                    hidden.update(range(start, end))
        return hidden

    def list(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._records if r.get("session_id") == session_id]


class ConversationMemory:
    """包装 Core MemoryStore：只改 history() 的读视图，其余原样委派。

    Core 与 YoAiAgent 持有的都是这个包装对象，因此模型上下文与 UI 快照
    都自然过滤掉撤回/编辑前的旧分支；新消息仍通过 append_history 写入底层。
    """

    def __init__(self, store: Any, actions: ConversationActions, session_id: str) -> None:
        self._store = store
        self._actions = actions
        self._session_id = session_id

    def history_full(self) -> list[Any]:
        """未过滤的原始历史，供动作命令定位索引。"""
        return list(self._store.history())

    def history_with_indices(self) -> list[tuple[int, Any]]:
        """返回 (原始序号, 消息)，供 UI 定位撤回/编辑目标。"""
        messages = self.history_full()
        hidden = self._actions.hidden_indices(self._session_id, len(messages))
        return [(i, m) for i, m in enumerate(messages) if i not in hidden]

    def history(self) -> list[Any]:
        return [message for _, message in self.history_with_indices()]

    async def append_history(self, message: Any) -> None:
        await self._store.append_history(message)

    async def put(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        await self._store.put(key, value, ttl_seconds)

    async def get(self, key: str) -> str | None:
        return await self._store.get(key)

    async def clear(self) -> None:
        await self._store.clear()
