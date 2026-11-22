"""会话身份与持久化测试。全部离线（ScriptedModel），零依赖。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:\Competition\YAI Agent Core") / "src"))

from yai_core import (  # noqa: E402
    EventType, ModelResponse, ScriptedModel, ToolCallRequest,
)

from yoai.session import SessionManager  # noqa: E402


def _factory(n: int = 1):
    def f():
        return ScriptedModel([ModelResponse(content=f"回答 {n}")])
    return f


def test_create_and_persist_identity(tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory())
    s = mgr.create("日报会话")
    assert s.id and s.name == "日报会话"
    assert mgr.current.id == s.id
    assert mgr.list_sessions()[0].id == s.id

    # 新管理器重载：身份还在
    mgr2 = SessionManager(tmp_path, model_factory=_factory())
    assert mgr2.current.id == s.id
    assert mgr2.get(s.id).name == "日报会话"


def test_multiple_sessions_isolated(tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory())
    s1 = mgr.create("A")
    s2 = mgr.create("B")
    assert s1.id != s2.id
    assert mgr.current.id == s2.id
    assert mgr.switch(s1.id) is True
    assert mgr.current.id == s1.id
    assert mgr.switch("nope") is False
    assert len(mgr.list_sessions()) == 2


def test_agent_instance_reused_per_session(tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory())
    s = mgr.create()
    a1 = mgr.agent_for()
    a2 = mgr.agent_for()
    assert a1 is a2   # 同一 session 复用实例 → 历史自然累积


def test_history_accumulates_within_session(tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory())
    mgr.create("会话 A")
    agent = mgr.current_agent()

    async def run(task):
        async for _ in agent.astream(task):
            pass

    asyncio.run(run("第一个问题"))
    asyncio.run(run("第二个问题"))
    # 每轮 user + assistant 两条历史
    assert mgr.history_len() >= 4


def test_history_isolated_between_sessions(tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory())
    s1 = mgr.create("A")
    s2 = mgr.create("B")

    async def run(agent, task):
        async for _ in agent.astream(task):
            pass

    a1 = mgr.agent_for(s1.id)
    asyncio.run(run(a1, "只在 A 说的秘密"))
    assert mgr.history_len(s1.id) >= 2
    assert mgr.history_len(s2.id) == 0   # B 的历史独立为空


def test_history_survives_restart(tmp_path):
    """跨启动恢复：新 SessionManager 重载后历史仍在。"""
    mgr = SessionManager(tmp_path, model_factory=_factory())
    s = mgr.create("持久会话")

    async def run(agent, task):
        async for _ in agent.astream(task):
            pass

    asyncio.run(run(mgr.current_agent(), "记住这段历史"))
    before = mgr.history_len(s.id)
    assert before > 0

    mgr2 = SessionManager(tmp_path, model_factory=_factory())
    assert mgr2.current.id == s.id
    assert mgr2.history_len(s.id) == before  # 历史跨启动保留


def test_shared_context_across_sessions(tmp_path):
    """个人事实跨会话共享（设计单：人格记忆不随专家/会话分裂）。"""
    mgr = SessionManager(tmp_path, model_factory=_factory())
    s1 = mgr.create("A")
    a1 = mgr.agent_for(s1.id)
    a1.context.remember("theme", "dark")

    s2 = mgr.create("B")
    a2 = mgr.agent_for(s2.id)
    assert a2.context.recall("theme") == "dark"   # 共享


def test_delete_session(tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory())
    s1 = mgr.create("A")
    mgr.create("B")
    assert mgr.delete(s1.id) is True
    assert mgr.get(s1.id) is None
    assert mgr.delete("nope") is False
    assert len(mgr.list_sessions()) == 1


def test_corrupt_index_isolated(tmp_path):
    (tmp_path / "sessions.json").write_text("{bad", encoding="utf-8")
    mgr = SessionManager(tmp_path, model_factory=_factory())
    assert mgr.list_sessions() == []
    assert (tmp_path / "sessions.json.corrupt").exists()
