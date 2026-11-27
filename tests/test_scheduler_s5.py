"""Scheduler S5：目标事件、每次运行的新上下文、定时运行的证据。不依赖 Core。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.goals import GoalManager  # noqa: E402
from yoai.scheduler.host import SchedulerHost  # noqa: E402
from yoai.scheduler.memory_window import RunWindowMemory  # noqa: E402
from yoai.scheduler.models import Job, Trigger  # noqa: E402


class Obj:
    def __init__(self, **kw) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


class Ev:
    def __init__(self, name, data) -> None:
        self.type = Obj(value=name)
        self.data = data


class ListMemory:
    """最小的 Core memory 替身：history / append_history / get / put。"""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.kv: dict[str, str] = {}

    def history(self):
        return list(self.messages)

    async def append_history(self, message) -> None:
        self.messages.append(message)

    async def put(self, key, value, ttl_seconds=None) -> None:
        self.kv[key] = value

    async def get(self, key):
        return self.kv.get(key)


class FakeAgent:
    def __init__(self, goals: GoalManager, memory=None) -> None:
        self.core = Obj(policy=Obj(mode="auto", allowed=set()), executor=Obj(policy=None), memory=memory)
        self.goals = goals
        self.seen_history: list[list[str]] = []
        self.prompts: list[str] = []
        self.on_run = None
        self.model = Obj(last_expert_id="root", last_parent_id=None, total_usage={"input": 3},
                         last_decision=Obj(to_dict=lambda: {"selected_id": "root"}))

    async def astream(self, prompt):
        self.prompts.append(prompt)
        mem = self.core.memory
        if mem is not None:
            self.seen_history.append(list(mem.history()))
            await mem.append_history(f"user:{prompt}")
        if self.on_run is not None:
            await self.on_run()
        if mem is not None:
            await mem.append_history("assistant:好的")
        yield Ev("tool_call", {"tool": "list_goals"})
        yield Ev("done", {"final_text": "好的", "status": "ok"})


class FakeSessions:
    def __init__(self, data_dir: Path, *, wrap=None) -> None:
        self.data_dir = data_dir
        self._s: dict[str, Obj] = {}
        self._agents: dict[str, FakeAgent] = {}
        self._current = None
        self._n = 0
        self.wrap = wrap
        self.create("新会话")

    def create(self, name=""):
        self._n += 1
        sid = f"s{self._n}"
        self._s[sid] = Obj(id=sid, name=name)
        self._current = sid
        return self._s[sid]

    def get(self, sid):
        return self._s.get(sid)

    def list_sessions(self):
        return list(self._s.values())

    @property
    def current(self):
        return self._s.get(self._current)

    def switch(self, sid):
        self._current = sid
        return True

    def agent_for(self, sid=None):
        sid = sid or self._current
        if sid not in self._agents:
            memory = ListMemory()
            if self.wrap is not None:
                memory = self.wrap(sid, memory)
            # 和真实 SessionManager 一样：每个会话一个 GoalManager，指向同一个共享文件
            self._agents[sid] = FakeAgent(GoalManager(self.data_dir / "goals.json"), memory)
        return self._agents[sid]

    def touch(self, sid=None, *, delta=1):
        pass


class FakeCollector:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.finished: dict | None = None

    def observe(self, ev) -> None:
        self.events.append(ev.type.value)

    def finish(self, **kw):
        self.finished = kw
        return Obj(id="ev-1", **kw)


class FakeEvidenceStore:
    def __init__(self) -> None:
        self.added: list = []
        self.attributions: list = []

    def add(self, evidence) -> None:
        self.added.append(evidence)

    def add_attribution(self, a) -> None:
        self.attributions.append(a)


def make(tmp_path, **kw):
    holder: dict = {}
    sessions = FakeSessions(tmp_path, wrap=lambda sid, mem: holder["host"].wrap_memory(sid, mem))
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    host = SchedulerHost(
        tmp_path, sessions, send, is_busy=kw.pop("is_busy", lambda: False),
        channel_factory=lambda cb: cb,
        policy_factory=lambda allowed: Obj(mode="auto", allowed=set(allowed)),
        clean_text=lambda s: s, tick_s=3600, provision=False, **kw,
    )
    host._fingerprint = lambda prompt: ("fp-" + str(len(prompt)), ("goal",))
    holder["host"] = host
    return host, sessions, sent


async def settle(host, rounds: int = 5) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0.01)
    await host.engine.wait_idle()


# ---------------- S5-1 目标事件 ----------------

def test_goal_created_in_user_session_fires_event_job(tmp_path):
    async def main():
        host, sessions, _sent = make(tmp_path)
        host.engine.add_job(Job(name="新目标", prompt="帮我拆解目标「{goal_title}」",
                                trigger=Trigger(kind="event", event="goal_created")))
        await host.start()
        user_agent = sessions.agent_for("s1")
        user_agent.goals.create_goal("学中文")          # 用户在普通会话里建目标
        await settle(host)
        sched = sessions.agent_for(host.session_id)
        assert sched.prompts == ["[定时任务 · 新目标]\n帮我拆解目标「学中文」"]
        rec = host.store.runs()[0]
        assert rec.state == "ok" and rec.reason == "event:goal_created"
        await host.shutdown()
    asyncio.run(main())


def test_goal_status_filter_and_listener_removed_on_shutdown(tmp_path):
    async def main():
        host, sessions, _sent = make(tmp_path)
        host.engine.add_job(Job(name="完成", prompt="庆祝「{goal_title}」",
                                trigger=Trigger(kind="event", event="goal_status_changed",
                                                params={"status": "done"})))
        await host.start()
        goals = sessions.agent_for("s1").goals
        gid = goals.create_goal("写论文")
        goals.set_status(gid, "active")
        await settle(host)
        assert host.store.runs() == []                    # 不是 done，不触发
        goals.set_status(gid, "done")
        await settle(host)
        assert [r.reason for r in host.store.runs()] == ["event:goal_status_changed"]
        await host.shutdown()
        goals.set_status(gid, "active")
        goals.set_status(gid, "done")
        await asyncio.sleep(0.05)
        assert len(host.store.runs()) == 1               # 停止后不再监听
    asyncio.run(main())


def test_event_waits_while_user_is_busy(tmp_path):
    async def main():
        busy = {"v": True}
        host, sessions, _sent = make(tmp_path, is_busy=lambda: busy["v"])
        host.engine.add_job(Job(name="新目标", prompt="p", trigger=Trigger(kind="event", event="goal_created")))
        await host.start()
        sessions.agent_for("s1").goals.create_goal("x")    # 正在对话中建的目标
        await settle(host)
        assert host.store.runs() == []
        busy["v"] = False
        await host.engine.tick()
        await settle(host)
        assert [r.state for r in host.store.runs()] == ["ok"]
        await host.shutdown()
    asyncio.run(main())


def test_goals_changed_by_scheduler_run_do_not_retrigger(tmp_path):
    async def main():
        host, sessions, _sent = make(tmp_path)
        host.engine.add_job(Job(name="新目标", prompt="p", trigger=Trigger(kind="event", event="goal_created")))
        await host.start()
        sched = sessions.agent_for(host.session_id)

        async def create_during_run():
            sched.goals.create_goal("定时任务自己建的")
        sched.on_run = create_during_run
        sessions.agent_for("s1").goals.create_goal("用户建的")
        await settle(host, rounds=10)
        assert len(host.store.runs(limit=0)) == 1         # 没有自己触发自己
        await host.shutdown()
    asyncio.run(main())


def test_stale_check_sees_goals_created_in_other_sessions(tmp_path):
    host, sessions, _sent = make(tmp_path)
    sessions.agent_for(host.session_id)                   # 定时任务会话先建好、一直缓存
    sessions.agent_for("s1").goals.create_goal("之后才建的目标")
    assert [g["title"] for g in host._goals()] == ["之后才建的目标"]


# ---------------- S5-3 每次运行新上下文 ----------------

def test_each_run_sees_only_its_own_messages(tmp_path):
    async def main():
        host, sessions, _sent = make(tmp_path)
        job = host.engine.add_job(Job(name="早间", prompt="列出目标", trigger=Trigger(kind="daily", time="09:00")))
        for _ in range(3):
            await host.engine.run_now(job.id)
            await host.engine.wait_idle()
        agent = sessions.agent_for(host.session_id)
        assert isinstance(agent.core.memory, RunWindowMemory)
        assert agent.seen_history == [[], [], []]          # 每次开始时都看不到之前的运行
        assert len(agent.core.memory.history()) == 6       # 运行结束后，界面能看到全部
    asyncio.run(main())


def test_fresh_context_can_be_turned_off(tmp_path):
    async def main():
        host, sessions, _sent = make(tmp_path, fresh_context=False)
        job = host.engine.add_job(Job(name="x", prompt="p", trigger=Trigger(kind="daily", time="09:00")))
        for _ in range(2):
            await host.engine.run_now(job.id)
            await host.engine.wait_idle()
        agent = sessions.agent_for(host.session_id)
        assert not isinstance(agent.core.memory, RunWindowMemory)
        assert len(agent.seen_history[1]) == 2              # 第二次能看到第一次
    asyncio.run(main())


def test_window_memory_delegates_and_user_sessions_are_not_wrapped(tmp_path):
    async def main():
        inner = ListMemory()
        w = RunWindowMemory(inner)
        await w.append_history("a")
        w.begin()
        await w.append_history("b")
        assert w.history() == ["b"] and w.history_with_indices() == [(1, "b")]
        w.end()
        assert w.history() == ["a", "b"]
        await w.put("k", "v")
        assert await w.get("k") == "v"
        host, sessions, _sent = make(tmp_path)
        assert not isinstance(sessions.agent_for("s1").core.memory, RunWindowMemory)
    asyncio.run(main())


# ---------------- S5-4 证据 ----------------

def test_scheduled_run_records_evidence(tmp_path):
    async def main():
        store = FakeEvidenceStore()
        collectors: list[FakeCollector] = []

        def factory():
            collectors.append(FakeCollector())
            return collectors[-1]
        host, _sessions, _sent = make(tmp_path, evidence_store=lambda: store, collector_factory=factory)
        job = host.engine.add_job(Job(name="早间", prompt="列出目标", trigger=Trigger(kind="daily", time="09:00")))
        await host.engine.run_now(job.id)
        await host.engine.wait_idle()
        c = collectors[0]
        assert c.events == ["tool_call", "done"]
        assert c.finished["task"] == "[定时任务 · 早间]\n列出目标"
        assert c.finished["task_fingerprint"] == "fp-4"       # 指纹只按任务内容算
        assert c.finished["sample_class"] == "evolution" and c.finished["expert_id"] == "root"
        assert c.finished["route_decision"] == {"selected_id": "root"}
        assert store.added and host.store.runs(job.id)[0].evidence_id == "ev-1"
    asyncio.run(main())


def test_no_evidence_store_means_no_collection_and_failures_dont_break_runs(tmp_path):
    async def main():
        host, _sessions, _sent = make(tmp_path)               # 没有证据库
        job = host.engine.add_job(Job(name="x", prompt="p", trigger=Trigger(kind="daily", time="09:00")))
        await host.engine.run_now(job.id)
        await host.engine.wait_idle()
        assert host.store.runs(job.id)[0].evidence_id == ""

        class Broken(FakeEvidenceStore):
            def add(self, evidence):
                raise OSError("磁盘满了")
        host2, _s2, _x = make(tmp_path / "b", evidence_store=Broken(), collector_factory=FakeCollector)
        job2 = host2.engine.add_job(Job(name="x", prompt="p", trigger=Trigger(kind="daily", time="09:00")))
        await host2.engine.run_now(job2.id)
        await host2.engine.wait_idle()
        rec = host2.store.runs(job2.id)[0]
        assert rec.state == "ok" and rec.evidence_id == ""
    asyncio.run(main())
