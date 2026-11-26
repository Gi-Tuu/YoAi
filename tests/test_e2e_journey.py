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


def test_message_actions_retract_and_edit(tmp_path):
    """撤回/编辑走软删除+分支：UI/模型读视图过滤，原始 Core 历史不动。"""
    from yoai.conversation_actions import ConversationActions, ConversationMemory

    actions = ConversationActions(tmp_path)
    messages = [
        SimpleNamespace(role="user", content="旧问题"),
        SimpleNamespace(role="assistant", content="旧回答"),
    ]
    store = SimpleNamespace(history=lambda: list(messages))
    memory = ConversationMemory(store, actions, "s1")
    rt = make_runtime(store_dir=tmp_path)
    rt.actions = actions
    rt.agent = SimpleNamespace(core=SimpleNamespace(memory=memory))

    out = collect(rt)
    run(rt.handle({"type": "message.retract", "index": 0}))
    assert any(m["type"] == "message.updated" and m["kind"] == "retract" for m in out)
    assert memory.history() == []

    # 编辑：旧区间隐藏，新任务按新文本调度
    actions.add(session_id="s1", kind="retract", hide_from=0, hide_until=0)
    captured = {}
    async def fake_start(task_id, run_id, text):
        captured.update(task_id=task_id, run_id=run_id, text=text)
    rt.start_task = fake_start  # type: ignore[method-assign]
    out.clear()
    run(rt.handle({"type": "message.edit", "index": 0, "input": "新问题",
                   "task_id": "t9", "run_id": "r9"}))
    assert any(m["type"] == "message.updated" and m["kind"] == "edit" for m in out)
    assert captured["text"] == "新问题"
    assert any(r["kind"] == "edit" for r in actions.list("s1"))


def test_share_export_writes_local_file(tmp_path):
    """分享只写本地 md/html，不生成公网链接。"""
    rt = make_runtime(store_dir=tmp_path)
    out = collect(rt)
    target = tmp_path / "share.md"
    run(rt.handle({"type": "share.export", "path": str(target),
                   "content": "# 分享\n\n内容", "count": 2}))
    assert target.read_text(encoding="utf-8") == "# 分享\n\n内容"
    exported = next(m for m in out if m["type"] == "share.exported")
    assert exported["count"] == 2


def test_archive_state_includes_evolution_reports(tmp_path, monkeypatch):
    """星图节点必须带进化审计与证据链，不能只显示一个光溜溜的星球。"""
    from yoai.evolution import EvolutionArchive, EvolutionReportStore, ExpertSpec

    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    archive = EvolutionArchive(tmp_path / "evolution" / "evolution.json")
    root = archive.create_root("root", ExpertSpec(prompt_suffix="通用"))
    store = EvolutionReportStore(tmp_path)
    store.add({"id": "rep1", "evidence_id": "e1", "triggered": True,
               "cause": "capability", "new_node_id": root.id,
               "reason": "候选已创建", "created_at": "2026-11-26T00:00:00Z"})
    rt = make_runtime(store_dir=tmp_path)
    rt.evolution_reports = store

    state = rt._archive_state()
    node = next(n for n in state["nodes"] if n["id"] == root.id)
    assert node["reports"][0]["id"] == "rep1"
    assert node["evidence"] == []


def test_feedback_record_binds_evidence(tmp_path, monkeypatch):
    """R0：用户动作写独立反馈信号，绑定对应执行证据，不影响进化档案。"""
    from yoai.evidence import ExecutionEvidence, EvidenceStore, FeedbackStore

    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    store = EvidenceStore(tmp_path / "evidence" / "evidence.json")
    evidence = ExecutionEvidence.create(
        session_id="s1", task="旧问题", task_fingerprint="fp1",
        fingerprint_tags=("temporal",), status="ok")
    store.add(evidence)
    rt = make_runtime(store_dir=tmp_path)
    rt.evidence_store = store
    rt.feedback_store = FeedbackStore(tmp_path)
    rt.run_evidence["r1"] = evidence.id

    out = collect(rt)
    run(rt.handle({"type": "feedback.record", "kind": "regenerate",
                   "task": "旧问题", "run_id": "r1"}))
    recorded = next(m for m in out if m["type"] == "feedback.recorded")
    assert recorded["signal"]["evidence_id"] == evidence.id
    assert recorded["signal"]["polarity"] == -1
    assert rt.feedback_store.count() == 1
    assert not any(m["type"] == "evolution.report" for m in out)


def test_boundary_get_pushes_state(tmp_path, monkeypatch):
    """R1：看板请求必须回 boundary.state，缺存储也要给空报告而不是崩溃。"""
    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    rt = make_runtime(store_dir=tmp_path)
    out = collect(rt)
    run(rt.handle({"type": "boundary.get"}))
    state = next(m for m in out if m["type"] == "boundary.state")
    assert state["report"]["rows"] == []
    assert state["report"]["total"] == 0


def test_rsi_trigger_command_reports_shadow_decisions(tmp_path, monkeypatch):
    """R2.1：空数据也必须回 rsi.triggered 并刷新看板，不崩溃。"""
    from yoai.evidence import EvidenceStore, FeedbackStore
    from yoai.evolution import EvolutionReportStore

    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    rt = make_runtime(store_dir=tmp_path)
    rt.evidence_store = EvidenceStore(tmp_path / "evidence.json")
    rt.feedback_store = FeedbackStore(tmp_path)
    rt.evolution_reports = EvolutionReportStore(tmp_path)
    out = collect(rt)
    run(rt.handle({"type": "rsi.trigger", "tags": []}))
    triggered = next(m for m in out if m["type"] == "rsi.triggered")
    assert triggered["decisions"] == []
    assert any(m["type"] == "archive.state" for m in out)
    assert any(m["type"] == "boundary.state" for m in out)


def test_rsi_validate_command_reports_result(tmp_path, monkeypatch):
    """R2.2：验证命令必须回结论并刷新档案，本阶段不改生命周期。"""
    from yoai.evidence import EvidenceStore
    from yoai.evolution import EvolutionReportStore

    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    rt = make_runtime(store_dir=tmp_path)
    rt.evidence_store = EvidenceStore(tmp_path / "evidence.json")
    rt.evolution_reports = EvolutionReportStore(tmp_path)
    out = collect(rt)
    run(rt.handle({"type": "rsi.validate", "node_id": "missing"}))
    validated = next(m for m in out if m["type"] == "rsi.validated")
    assert validated["validation"]["verdict"] == "insufficient"
    assert validated["validation"]["promoted"] is False
    promoted = next(m for m in out if m["type"] == "rsi.promoted")
    assert promoted["decision"]["verdict"] == "insufficient"
    assert promoted["decision"]["changed"] is False
    assert any(m["type"] == "archive.state" for m in out)


def test_rsi_trial_commands(tmp_path, monkeypatch):
    """R3.2：trial 命令必须回状态并刷新档案，证据不足时拒绝批准。"""
    from yoai.evidence import EvidenceStore, FeedbackStore
    from yoai.evolution import (
        EvolutionArchive, EvolutionReportStore, ExpertSpec, TrialStore,
    )

    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    rt = make_runtime(store_dir=tmp_path)
    rt.evidence_store = EvidenceStore(tmp_path / "evidence.json")
    rt.feedback_store = FeedbackStore(tmp_path)
    rt.evolution_reports = EvolutionReportStore(tmp_path)
    rt.trial_store = TrialStore(tmp_path)
    archive = EvolutionArchive(tmp_path / "evolution" / "evolution.json")
    root = archive.create_root("root", ExpertSpec())
    child = archive.create_child(root.id, "child",
                                 ExpertSpec(), diff={"dimension": "tools", "tag": "temporal"})
    archive.transition(child.id, "probation")

    out = collect(rt)
    run(rt.handle({"type": "rsi.trial_start", "node_id": child.id,
                   "scope": "tag:temporal", "max_n": 20}))
    started = next(m for m in out if m["type"] == "trial.state")
    assert started["trial"]["node_id"] == child.id
    assert started["trial"]["status"] == "running"

    out.clear()
    run(rt.handle({"type": "rsi.trial_report", "trial_id": started["trial"]["id"]}))
    report = next(m for m in out if m["type"] == "trial.report")
    assert report["report"]["passed"] is False

    out.clear()
    run(rt.handle({"type": "rsi.promote_active", "trial_id": started["trial"]["id"],
                   "approved_by": "tester"}))
    assert any(m["type"] == "error" and "硬门槛" in m["message"] for m in out)
    assert archive.get(child.id).lifecycle == "probation"


def test_rsi_rollback_command_reports_decision(tmp_path, monkeypatch):
    """R3.3：手动回滚检查必须回结论并刷新档案。"""
    from yoai.evidence import EvidenceStore, FeedbackStore
    from yoai.evolution import EvolutionReportStore

    monkeypatch.setattr(yoai_runtime, "_data_dir", lambda: tmp_path)
    rt = make_runtime(store_dir=tmp_path)
    rt.evidence_store = EvidenceStore(tmp_path / "evidence.json")
    rt.feedback_store = FeedbackStore(tmp_path)
    rt.evolution_reports = EvolutionReportStore(tmp_path)
    out = collect(rt)
    run(rt.handle({"type": "rsi.rollback", "node_id": "missing"}))
    rolled = next(m for m in out if m["type"] == "rsi.rolled_back")
    assert rolled["decision"]["rolled_back"] is False
    assert any(m["type"] == "archive.state" for m in out)


def test_mcp_management_commands(tmp_path):
    """MCP 状态/配置/重载命令必须通过协议层可用。"""
    from types import SimpleNamespace

    calls = []
    manager = SimpleNamespace(
        path=tmp_path / "mcp" / "servers.json",
        status=lambda: {"servers": {}, "tools": [], "config": str(tmp_path)},
        refresh=lambda: calls.append("refresh"),
    )
    rt = make_runtime(store_dir=tmp_path)
    rt.mcp_manager = manager
    out = collect(rt)

    run(rt.handle({"type": "mcp.status"}))
    assert next(m for m in out if m["type"] == "mcp.state")["status"]["tools"] == []

    out.clear()
    run(rt.handle({"type": "mcp.config_get"}))
    cfg = next(m for m in out if m["type"] == "mcp.config")
    assert "servers" in cfg["text"]

    out.clear()
    run(rt.handle({"type": "mcp.config_set", "text": '{"servers": []}'}))
    assert manager.path.read_text(encoding="utf-8") == '{"servers": []}'
    assert any(m["type"] == "mcp.ack" for m in out)
    assert calls == ["refresh"]

    out.clear()
    run(rt.handle({"type": "mcp.reload"}))
    assert calls == ["refresh", "refresh"]


def test_skill_management_commands(tmp_path):
    """Skill 状态/配置/重载命令必须通过协议层可用。"""
    from yoai.skills import SkillStore

    rt = make_runtime(store_dir=tmp_path)
    rt.skill_store = SkillStore(tmp_path)
    out = collect(rt)

    run(rt.handle({"type": "skill.status"}))
    assert next(m for m in out if m["type"] == "skill.state")["status"]["skills"] == []

    out.clear()
    run(rt.handle({"type": "skill.config_get"}))
    assert "skills" in next(m for m in out if m["type"] == "skill.config")["text"]

    out.clear()
    run(rt.handle({"type": "skill.config_set", "text": '{"skills": [{"name":"s"}]}'}))
    assert any(m["type"] == "skill.ack" for m in out)
    state = next(m for m in out if m["type"] == "skill.state")
    assert [s["name"] for s in state["status"]["skills"]] == ["s"]

    out.clear()
    run(rt.handle({"type": "skill.reload"}))
    assert any(m["type"] == "skill.ack" for m in out)
