"""用户旅程守护测试（2026-11-25）：拦住"接线类"回归。

今天连续翻的车全是同一类——能力在，线没接对：
1. start_task 定义 _run 却漏 create_task → 任务从不执行
2. App.onMessage 漏 setMsgs → 快照/事件进不了 UI
3. 流式/非流式 tool_calls 格式不一致 → 工具调用静默丢弃
4. request_capability 注册了没标 meta_tool → 报"应由 Loop 处理"
5. YOAI_READONLY_ROOTS 没开 → file_ro_* 未注册
6. 数据目录/网关路径自举错 → 旧会话不可见、网关静默降级
7. 空数据目录首次启动 KeyError

本文件用假 agent 跑 Runtime 的完整命令→事件链路（不联网），
任何一处接线断了都会红。前端链路由 tests/app-snapshot.test.tsx 守。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
_TAURI = _ROOT / "apps" / "desktop-tauri" / "runtime"
sys.path.insert(0, str(_TAURI))

import yoai_runtime  # noqa: E402
from protocol import PROTOCOL_VERSION  # noqa: E402
from yoai.models.suanli_adapter import flatten_stream_tool_calls  # noqa: E402


# ---------------- 假件 ----------------

class FakeAgent:
    """最小 agent：可产出 thinking / delta / tool_call / done。"""

    def __init__(self, script: list[tuple[str, dict[str, Any]]]) -> None:
        self.script = script
        self.calls: list[str] = []

    async def astream(self, task: str):
        for name, data in self.script:
            yield SimpleNamespace(type=SimpleNamespace(value=name), data=data)

    def list_tools(self) -> list[str]:
        return ["remember_fact", "file_ro_list"]

    def _config(self):  # 让 resolve_model_name 走通
        return ("", "", "fake-model")

    # snapshot 需要的属性（假件）
    @property
    def core(self):
        return SimpleNamespace(memory=SimpleNamespace(history=lambda: []))

    @property
    def context(self):
        return SimpleNamespace(list_all=lambda: {})

    @property
    def goals(self):
        return SimpleNamespace(list_goals=lambda: [])

    # snapshot 需要的属性（假件）
    @property
    def core(self):
        return SimpleNamespace(memory=SimpleNamespace(history=lambda: []))

    @property
    def context(self):
        return SimpleNamespace(list_all=lambda: {})

    @property
    def goals(self):
        return SimpleNamespace(list_goals=lambda: [])


class FakeSession:
    def __init__(self, sid: str = "s1") -> None:
        self.id = sid
        self.name = "新会话"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


class FakeSessions:
    def __init__(self) -> None:
        self.current = FakeSession()
        self.created = 0
        self.switched = ""
        self.renamed = ""
        self.deleted = ""

    def list_sessions(self):
        return [self.current]

    def current_agent(self):
        return self._agent

    def create(self, name: str = "") -> FakeSession:
        self.created += 1
        self.current = FakeSession(f"s{self.created + 1}")
        return self.current

    def switch(self, sid: str) -> bool:
        self.switched = sid
        self.current = FakeSession(sid)
        return True

    def rename(self, sid: str, name: str) -> bool:
        self.renamed = name
        return bool(name.strip())

    def delete(self, sid: str) -> bool:
        self.deleted = sid
        return True


class FakeChannel:
    def __init__(self) -> None:
        self.peers: dict[str, Any] = {}
        self.sent: list[str] = []

    def groups(self):
        return []

    def history(self, target: str = ""):
        return []

    async def send(self, message):
        self.sent.append(str(message))
        return []


def make_runtime(script: list[tuple[str, dict[str, Any]]] | None = None,
                 store_dir: Path | None = None):
    """构造一个不联网、已注入假件的 Runtime。"""
    rt = yoai_runtime.Runtime()
    rt.agent = FakeAgent(script or [("done", {"final_text": "完成"})])
    rt.sessions = FakeSessions()
    rt.sessions._agent = rt.agent
    rt.channel = FakeChannel()
    rt.registry = {}
    from yoai.thinking_store import ThinkingStore
    rt.thinking_store = ThinkingStore(store_dir or (_ROOT / "output"))
    return rt


def collect(rt: yoai_runtime.Runtime) -> list[dict[str, Any]]:
    """接管 send，收集所有协议消息（不写 stdout）。"""
    out: list[dict[str, Any]] = []

    async def fake_send(msg):
        out.append(msg)

    rt.send = fake_send  # type: ignore[method-assign]
    return out


def run(coro):
    return asyncio.run(coro)


# ---------------- 旅程 1：握手三件套 ----------------

def test_journey_hello_emits_ready_snapshot_chat_state():
    """hello 必须同时回 ready + snapshot + chat.state——少一个 UI 就空。"""
    rt = make_runtime()
    out = collect(rt)
    run(rt.handle({"type": "hello"}))
    types = [m["type"] for m in out]
    assert types[:3] == ["ready", "snapshot", "chat.state"], types

    snap = next(m for m in out if m["type"] == "snapshot")
    # snapshot 必须带齐侧栏所需字段（漏一个前端就显示"…"/"无会话"）
    for key in ("sessions", "current_id", "history", "model", "facts",
                "goals", "write_stats", "tools", "thinking_log"):
        assert key in snap, f"snapshot 缺字段: {key}"
    assert snap["model"] == "fake-model"


# ---------------- 旅程 2：任务真的被调度 ----------------

def test_journey_task_actually_runs(tmp_path):
    """回归今天最致命 bug：_run 定义了却没 create_task，只发 running 就死。"""
    script = [
        ("thinking", {"text": "想想"}),
        ("delta", {"round": 0, "text": "你"}),
        ("delta", {"round": 0, "text": "好"}),
        ("tool_call", {"tool": "remember_fact", "arguments": {"key": "k"}}),
        ("tool_result", {"tool": "remember_fact", "result": "ok"}),
        ("done", {"final_text": "你好，完成"}),
    ]
    rt = make_runtime(script, store_dir=tmp_path)
    out = collect(rt)
    run(rt.handle({"type": "task.start", "task_id": "t1", "run_id": "r1",
                   "input": "测试"}))

    # 关键：_run 必须真的跑起来（不是只有 status running）
    names = [m.get("event") for m in out if m["type"] == "event"]
    assert "thinking" in names, f"thinking 丢了: {names}"
    assert "delta" in names and names.count("delta") == 2, names
    assert "tool_call" in names and "tool_result" in names, names

    # final 到、status done、并刷新快照
    finals = [m for m in out if m["type"] == "final"]
    assert len(finals) == 1 and finals[0]["text"] == "你好，完成"
    assert any(m["type"] == "status" and m["state"] == "done" for m in out)
    assert any(m["type"] == "snapshot" for m in out), "done 后必须刷新快照"

    # thinking 必须被累积并落盘
    assert rt.think_buffer == {}  # finally 清理了
    log = rt.thinking_store.load("s1") if rt.thinking_store else []
    assert len(log) == 1 and log[0]["text"] == "想想", log


def test_journey_final_empty_falls_back_to_stream():
    """final 空但有 delta → 用流式文本兜底（网关差异场景）。"""
    rt = make_runtime([
        ("delta", {"round": 0, "text": "流式兜底文本"}),
        ("done", {"final_text": ""}),
    ])
    out = collect(rt)
    run(rt.handle({"type": "task.start", "task_id": "t", "run_id": "r", "input": "x"}))
    finals = [m for m in out if m["type"] == "final"]
    assert finals and finals[0]["text"] == "流式兜底文本"


# ---------------- 旅程 3：会话管理四件套 ----------------

def test_journey_session_lifecycle_always_pushes_snapshot():
    """create/switch/rename/delete 每个都必须回推 snapshot（否则 UI 不同步）。"""
    rt = make_runtime()
    out = collect(rt)
    run(rt.handle({"type": "hello"}))
    n = len([m for m in out if m["type"] == "snapshot"])

    for cmd in (
        {"type": "session.create", "name": "新会话"},
        {"type": "session.switch", "session_id": "s2"},
        {"type": "session.rename", "session_id": "s1", "name": "改名"},
        {"type": "session.delete", "session_id": "s2"},
    ):
        run(rt.handle(cmd))
        m = [x for x in out if x["type"] == "snapshot"]
        assert len(m) == n + 1, f"{cmd['type']} 没回推 snapshot"
        n += 1


# ---------------- 旅程 4：审批闭环 ----------------

def test_journey_approval_reply_resumes_task():
    """审批请求→回复必须唤醒等待的 future（否则任务永远卡住）。"""
    rt = make_runtime()
    out = collect(rt)

    async def scenario():
        async def requester():
            return await rt._request_host(
                "approval/request", {"tool": "file_create", "arguments": {}})
        task = asyncio.create_task(requester())
        await asyncio.sleep(0.01)
        assert len(rt.pending_approvals) == 1
        await rt.handle({"type": "approval.reply", "allow": True})
        assert await task is True
        assert rt.pending_approvals == {}

    run(scenario())
    reqs = [m for m in out if m["type"] == "approval.request"]
    assert len(reqs) == 1 and reqs[0]["tool"] == "file_create"


# ---------------- 旅程 5：工具调用格式契约 ----------------

def test_journey_stream_tool_calls_reach_provider():
    """回归今天的静默失败：流式嵌套格式必须扁平化后才能被 provider 消费。"""
    from yoai.adapters.base import AdapterResult, PeerAdapter
    from yoai.models import GatewayModelProvider

    calls = flatten_stream_tool_calls({
        0: {"id": "c1", "function": {"name": "remember_fact",
             "arguments": '{"key":"k","value":"v"}'}},
    })

    class Stub(PeerAdapter):
        level = "L2"
        def __init__(self): super().__init__("stub")
        def available(self): return True
        def send(self, message):
            return AdapterResult(True, text="", level="L2", tool_calls=calls)

    resp = asyncio.run(GatewayModelProvider(Stub()).achat(
        [{"role": "user", "content": "记住 k=v"}]))
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "remember_fact"
    assert resp.tool_calls[0].arguments == {"key": "k", "value": "v"}


# ---------------- 旅程 6：数据/网关路径自举 ----------------

def test_journey_core_src_env_normalization(monkeypatch):
    """生产 YAI_CORE_SRC 指 Core/src 时必须规范成根（否则网关静默降级）。"""
    core_root = Path(_ROOT.parent) / "Competition" / "YAI Agent Core"
    if not (core_root / "src" / "yai_core").is_dir():
        pytest.skip("本机无 Core 源码树")
    monkeypatch.setenv("YAI_CORE_SRC", str(core_root / "src"))
    # 重新加载模块以触发自举（模块级代码）
    import importlib
    mod = importlib.reload(yoai_runtime)
    assert Path(mod._core_src_candidates()[0]).name == "src"
    assert (Path(mod._core_src_candidates()[0]) / "yai_core").is_dir()
    assert str(core_root / "src") in sys.path


def test_journey_empty_data_dir_creates_initial_session(tmp_path, monkeypatch):
    """空数据目录首次启动不能 KeyError（旧端有 create 语义，搬迁曾漏）。"""
    monkeypatch.setenv("YOAI_DATA_DIR", str(tmp_path))
    rt = make_runtime()
    # 模拟 _ensure_agent 里的建会话分支（用真 SessionManager 避免依赖网关）
    from yoai.session import SessionManager
    sessions = SessionManager(tmp_path / "sessions", model_factory=lambda: FakeAgent([]))
    assert sessions.list_sessions() == []
    sessions.create("新会话")
    assert len(sessions.list_sessions()) == 1
    assert sessions.current_agent() is not None


# ---------------- 旅程 7：右侧工具方格 ----------------

def test_tool_dock_fs_commands(tmp_path, monkeypatch):
    """查看文件：列目录/读文本/越界拒绝——面板只读且锁在工作区内。"""
    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    rt = make_runtime(store_dir=tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "note.txt").write_text("你好文件", encoding="utf-8")
    (workspace / "sub").mkdir()
    (tmp_path / "outside.txt").write_text("不可读", encoding="utf-8")

    out = collect(rt)
    run(rt.handle({"type": "fs.list", "path": ""}))
    tree = next(m for m in out if m["type"] == "file.tree")
    assert tree["label"] == "工作区" and tree["path"] == ""
    assert {e["name"] for e in tree["entries"]} == {"note.txt", "sub"}

    out.clear()
    run(rt.handle({"type": "fs.read", "path": "note.txt"}))
    content = next(m for m in out if m["type"] == "file.content")
    assert content["content"] == "你好文件" and content["truncated"] is False

    out.clear()
    run(rt.handle({"type": "fs.read", "path": "../outside.txt"}))
    assert any(m["type"] == "error" and m["stage"] == "file" for m in out)
    assert not any(m["type"] == "file.content" for m in out)


def test_tool_dock_browser_open(monkeypatch):
    """系统浏览器兜底只放 http/https；file:// 必须拒绝。"""
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: True)
    rt = make_runtime()

    out = collect(rt)
    run(rt.handle({"type": "browser.open", "url": "https://example.com"}))
    opened = next(m for m in out if m["type"] == "browser.opened")
    assert opened["url"] == "https://example.com"

    out.clear()
    run(rt.handle({"type": "browser.open", "url": "file:///etc/passwd"}))
    assert any(m["type"] == "error" and m["stage"] == "browser" for m in out)
    assert not any(m["type"] == "browser.opened" for m in out)
