"""会话身份与持久化 · 让对话继续而不是每次新开。

设计依据（探测 Core 源码确认）：
- Core 的会话历史存在 MemoryStore；loop 每轮 append_history，下次任务从 history() 读。
- SqliteStore 原生支持 scope 列做会话隔离（history/kv 都按 scope 分区）。
- 一个 AgentCore 实例 = 一条串行会话（Core 并发契约）。

因此：一个 YoAi session = 一个 AgentCore 实例 + 一个 SqliteStore(scope=session_id)。
session_id 是稳定 uuid，元数据落盘；切换会话就是切到对应的 agent 实例。
个人事实（PersonalContext/Goals）跨会话共享，不随 session 分裂（符合设计单"人格记忆共享"）。
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from yai_core.memory import SqliteStore

from yoai.agent import YoAiAgent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    """一条会话的元数据（身份）。历史正文在 SqliteStore，不在这里。"""

    id: str
    name: str
    created_at: str
    last_active: str
    message_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "created_at": self.created_at, "last_active": self.last_active,
            "message_count": self.message_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        return cls(
            id=d["id"], name=d.get("name", ""),
            created_at=d.get("created_at", ""), last_active=d.get("last_active", ""),
            message_count=int(d.get("message_count", 0)),
        )


class SessionManager:
    """管理多条会话：身份、实例缓存、切换、持久化。"""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        model_factory: Callable[[], Any],
        shared_context_dir: str | Path | None = None,
        agent_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.data_dir / "sessions.json"
        self._history_dir = self.data_dir / "history"
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._model_factory = model_factory
        # 构造 agent 时透传的额外参数（如 builtin_tools / workspace_root）。
        # 桌面端必须显式传，否则 session 里的 agent 用默认参数、工具开不起来。
        self._agent_kwargs: dict[str, Any] = dict(agent_kwargs or {})
        self.shared_context_dir = Path(shared_context_dir) if shared_context_dir else self.data_dir / "shared"
        self._sessions: dict[str, Session] = {}
        self._agents: dict[str, YoAiAgent] = {}   # session_id -> 实例缓存
        self._current_id: str | None = None
        self._load_index()

    # --- 索引持久化 ---
    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            self._sessions = {
                d["id"]: Session.from_dict(d)
                for d in raw.get("sessions", []) if isinstance(d, dict)
            }
            self._current_id = raw.get("current_id")
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            backup = self._index_path.with_suffix(".json.corrupt")
            try:
                self._index_path.replace(backup)
            except OSError:
                pass
            self._sessions, self._current_id = {}, None

    def _save_index(self) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=str(self.data_dir), prefix=".yoai-sessions-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({
                    "current_id": self._current_id,
                    "sessions": [s.to_dict() for s in self._sessions.values()],
                }, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._index_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # --- 会话 CRUD ---
    def create(self, name: str = "") -> Session:
        sid = uuid.uuid4().hex[:12]
        now = _now()
        session = Session(id=sid, name=name or f"会话 {len(self._sessions) + 1}",
                          created_at=now, last_active=now)
        self._sessions[sid] = session
        self._current_id = sid
        self._save_index()
        return session

    def list_sessions(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.last_active, reverse=True)

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    @property
    def current(self) -> Session | None:
        return self._sessions.get(self._current_id) if self._current_id else None

    def switch(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._current_id = session_id
        self._sessions[session_id].last_active = _now()
        self._save_index()
        return True

    def rename(self, session_id: str, name: str) -> bool:
        session = self.get(session_id)
        name = name.strip()
        if session is None or not name:
            return False
        previous = session.name
        session.name = name
        try:
            self._save_index()
        except OSError:
            session.name = previous
            raise
        return True

    def delete(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._sessions.pop(session_id)
        self._agents.pop(session_id, None)
        # 历史文件保留（不物理删除，避免误删；仅移出路由）
        if self._current_id == session_id:
            self._current_id = next(iter(self._sessions), None)
        self._save_index()
        return True

    # --- 实例（懒加载 + 缓存）---
    def agent_for(self, session_id: str | None = None) -> YoAiAgent:
        """取会话的 agent 实例；同一 session 复用同一实例（历史自然累积）。"""
        sid = session_id or self._current_id
        if not sid or sid not in self._sessions:
            raise KeyError("没有活动会话，请先 create() 或 switch()")

        if sid not in self._agents:
            # 每个 session 独立 SqliteStore(scope=sid) → 历史按会话隔离、跨启动持久化
            store = SqliteStore(self._history_dir / f"{sid}.db", scope=sid)
            agent = YoAiAgent(
                model=self._model_factory(),
                data_dir=self.shared_context_dir,   # 个人事实/目标跨会话共享
                memory=store,                        # 构造时传入，Core loop 才会绑定
                **self._agent_kwargs,                # 桌面端在此注入 builtin_tools 等
            )
            self._agents[sid] = agent

        self._sessions[sid].last_active = _now()
        self._save_index()
        return self._agents[sid]

    def current_agent(self) -> YoAiAgent:
        return self.agent_for()

    def touch(self, session_id: str | None = None, *, delta: int = 1) -> None:
        sid = session_id or self._current_id
        if sid and sid in self._sessions:
            self._sessions[sid].message_count += delta
            self._sessions[sid].last_active = _now()
            self._save_index()

    def history_len(self, session_id: str | None = None) -> int:
        """从持久化记忆读该会话历史条数（跨会话恢复验证用）。"""
        sid = session_id or self._current_id
        if not sid or sid not in self._sessions:
            return 0
        store = SqliteStore(self._history_dir / f"{sid}.db", scope=sid)
        return len(store.history())

    def status(self) -> dict[str, Any]:
        return {
            "total": len(self._sessions),
            "current_id": self._current_id,
            "names": [s.name for s in self.list_sessions()],
        }
