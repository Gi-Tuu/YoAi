"""Scheduler S2 桥测试：假会话 / 假 agent，不联网、不依赖 Core。"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.scheduler.__main__ import main as cli_main  # noqa: E402
from yoai.scheduler.host import CLARIFY_UNATTENDED, SchedulerHost, disabled_message  # noqa: E402
from yoai.scheduler.models import SCHEDULER_SESSION_NAME, Job, Trigger  # noqa: E402
from yoai.scheduler.store import SchedulerStore  # noqa: E402

CN = timezone(timedelta(hours=8))


# ---------------- 假件 ----------------

class Obj:
    def __init__(self, **kw) -> None:
        for key, value in kw.items():
            setattr(self, key, value)


class Ev:
    def __init__(self, name, data) -> None:
        self.type = Obj(value=name)
        self.data = data


class FakeAgent:
    def __init__(self) -> None:
        self.core = Obj(policy=Obj(mode="allow_all", allowed=set()), executor=Obj(policy=None))
        self.prompts: list[str] = []
        self.script = [("delta", {"text": "流式"}), ("done", {"final_text": "完成了", "status": "ok"})]
        self.before_done = None          # 可在运行中模拟审批 / 澄清
        self.goals = Obj(list_goals=lambda: [])

    async def astream(self, prompt):
        self.prompts.append(prompt)
        for name, data in self.script:
            if name == "done" and self.before_done is not None:
                await self.before_done()
            yield Ev(name, data)


class FakeSessions:
    def __init__(self) -> None:
        self._s: dict[str, Obj] = {}
        self._agents: dict[str, FakeAgent] = {}
        self._current = None
        self._counter = 0
        self.touched: list[str] = []
        self.create("新会话")

    def create(self, name=""):
        self._counter += 1                     # 计数器：删除后也不会复用旧 id
        sid = f"s{self._counter}"
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

    def delete(self, sid):
        self._s.pop(sid, None)
        self._agents.pop(sid, None)

    def agent_for(self, sid=None):
        sid = sid or self._current
        if sid not in self._s:
            raise KeyError(sid)
        return self._agents.setdefault(sid, FakeAgent())

    def touch(self, sid=None, *, delta=1):
        self.touched.append(sid)


def make_host(tmp_path, **kw):
    sessions = kw.pop("sessions", None) or FakeSessions()
    sent: list[dict] = []
    calls = {"fallback": [], "history": 0}

    async def send(msg):
        sent.append(msg)

    async def fallback(kind, payload):
        calls["fallback"].append((kind, payload))
        return True

    def history():
        calls["history"] += 1

    host = SchedulerHost(
        tmp_path, sessions, send, is_busy=lambda: False,
        channel_factory=lambda cb: cb, fallback_request=fallback,
        policy_factory=lambda allowed: Obj(mode="auto", allowed=set(allowed)),
        clean_text=lambda s: s, on_history_changed=history, **kw,
    )
    return host, sessions, sent, calls


def types(sent):
    return [m["type"] for m in sent]


# ---------------- 会话与预置 ----------------

def test_dedicated_session_created_once_without_switching_user(tmp_path):
    host, sessions, _sent, _calls = make_host(tmp_path)
    assert sessions.current.id == "s1"                      # 用户还在原会话
    assert sessions.get(host.session_id).name == SCHEDULER_SESSION_NAME
    host2, _s, _x, _y = make_host(tmp_path, sessions=sessions)
    assert host2.session_id == host.session_id               # 不重复建
    assert len(sessions.list_sessions()) == 2


def test_heartbeat_preset_is_provisioned_once_and_off(tmp_path):
    host, sessions, _sent, _calls = make_host(tmp_path)
    hb = host.store.get("heartbeat")
    assert hb is not None and hb.enabled is False
    host.engine.remove_job("heartbeat")                      # 用户删掉
    host2, _s, _x, _y = make_host(tmp_path, sessions=sessions)
    assert host2.store.get("heartbeat") is None              # 不再自动出现


def test_agent_overrides_are_unattended(tmp_path):
    host, sessions, _sent, _calls = make_host(tmp_path)
    over = host.agent_overrides()
    assert over["channel"] is host.channel
    assert over["policy"].mode == "auto"
    assert "list_goals" in over["policy"].allowed and "shell_run" not in over["policy"].allowed
    agent = sessions.agent_for(host.session_id)
    assert host.owns(agent) and not host.owns(sessions.agent_for("s1"))


# ---------------- 运行 ----------------

def test_run_now_executes_in_dedicated_session_with_locked_policy(tmp_path):
    async def main():
        host, sessions, sent, calls = make_host(tmp_path)
        job = host.engine.add_job(Job(name="早间回顾", trigger=Trigger(kind="daily", time="09:00"),
                                      prompt="列出目标", allowed_tools=["shell_run", "custom"]))
        agent = sessions.agent_for(host.session_id)

        async def try_tools():
            assert await host.channel("approval/request", {"tool": "shell_run"}) is False
            assert await host.channel("approval/request", {"tool": "custom"}) is True
            assert await host.channel("clarify/request", {"question": "哪个?"}) == CLARIFY_UNATTENDED
        agent.before_done = try_tools

        await host.handle("schedule.run_now", {"job_id": job.id})
        await host.engine.wait_idle()

        assert agent.prompts == ["[定时任务 · 早间回顾]\n列出目标"]
        assert agent.core.policy.mode == "auto"                       # 原来是 allow_all
        assert "shell_run" not in agent.core.policy.allowed           # 黑名单无法放行
        assert "custom" in agent.core.policy.allowed
        assert agent.core.executor.policy is agent.core.policy
        rec = host.store.runs(job.id)[0]
        assert rec.state == "ok" and rec.summary == "完成了"
        assert rec.denied_tools == ["shell_run"]
        assert sessions.current.id == "s1"                             # 没切走用户会话
        assert calls["history"] == 1 and calls["fallback"] == []
        assert {"schedule.ack", "schedule.run_started", "schedule.run_finished",
                "schedule.state"} <= set(types(sent))
    asyncio.run(main())


def test_channel_falls_back_to_popup_when_not_running(tmp_path):
    async def main():
        host, _sessions, _sent, calls = make_host(tmp_path)
        assert await host.channel("approval/request", {"tool": "proj_write"}) is True
        assert calls["fallback"] == [("approval/request", {"tool": "proj_write"})]
    asyncio.run(main())


def test_error_status_and_missing_done_are_failures(tmp_path):
    async def main():
        host, sessions, _sent, _calls = make_host(tmp_path)
        job = host.engine.add_job(Job(name="x", trigger=Trigger(kind="daily", time="09:00"), prompt="p"))
        agent = sessions.agent_for(host.session_id)
        agent.script = [("error", {"message": "网关 502"}), ("done", {"final_text": "", "status": "error"})]
        await host.engine.run_now(job.id)
        await host.engine.wait_idle()
        rec = host.store.runs(job.id)[0]
        assert rec.state == "failed" and "网关 502" in rec.summary

        agent.script = [("delta", {"text": "半截"})]                      # 没有 done
        await host.engine.run_now(job.id)
        await host.engine.wait_idle()
        rec = host.store.runs(job.id)[0]
        assert rec.state == "failed" and "未收到完成事件" in rec.summary
    asyncio.run(main())


def test_deleted_dedicated_session_is_recreated(tmp_path):
    async def main():
        host, sessions, _sent, _calls = make_host(tmp_path)
        old = host.session_id
        sessions.delete(old)
        job = host.engine.add_job(Job(name="x", trigger=Trigger(kind="daily", time="09:00"), prompt="p"))
        await host.engine.run_now(job.id)
        await host.engine.wait_idle()
        assert host.session_id != old and sessions.get(host.session_id) is not None
        assert host.store.runs(job.id)[0].state == "ok"
    asyncio.run(main())


# ---------------- 命令 ----------------

def test_commands_save_toggle_runs_delete(tmp_path):
    async def main():
        host, _sessions, sent, _calls = make_host(tmp_path)
        await host.handle("schedule.save", {"job": {
            "name": "工作日提醒", "prompt": "看看今天的目标",
            "trigger": {"kind": "weekly", "weekdays": [0, 1, 2, 3, 4], "time": "08:30"}}})
        ack = [m for m in sent if m["type"] == "schedule.ack"][-1]
        assert ack["ok"] and "已创建" in ack["message"]
        job = next(j for j in host.store.list_jobs() if j.name == "工作日提醒")

        await host.handle("schedule.save", {"job": {"id": job.id, "prompt": "改过的内容",
                                                    "consecutive_failures": 99}})
        edited = host.store.get(job.id)
        assert edited.prompt == "改过的内容" and edited.consecutive_failures == 0  # 只改可编辑字段

        await host.handle("schedule.toggle", {"job_id": job.id, "enabled": False})
        assert host.store.get(job.id).enabled is False

        await host.handle("schedule.save", {"job": {"name": "", "prompt": "x",
                                                    "trigger": {"kind": "daily", "time": "9点"}}})
        bad = [m for m in sent if m["type"] == "schedule.ack"][-1]
        assert bad["ok"] is False and bad["message"]

        await host.handle("schedule.runs", {"job_id": job.id})
        assert [m for m in sent if m["type"] == "schedule.runs"][-1]["runs"] == []

        await host.handle("schedule.delete", {"job_id": job.id})
        assert host.store.get(job.id) is None
        state = [m for m in sent if m["type"] == "schedule.state"][-1]
        assert state["session_name"] == SCHEDULER_SESSION_NAME and all(m["v"] == 1 for m in sent)
    asyncio.run(main())


def test_start_marks_interrupted_and_pushes_state(tmp_path):
    async def main():
        host, _sessions, sent, _calls = make_host(tmp_path, tick_s=3600)
        await host.start()
        await host.start()                                    # 幂等
        assert types(sent).count("schedule.state") == 1
        await host.shutdown()
    asyncio.run(main())


# ---------------- 命令行 ----------------

def test_cli_add_list_enable_remove(tmp_path):
    data = tmp_path / "data"
    assert cli_main(["--data-dir", str(data), "add", "--name", "两分钟后", "--prompt", "列出目标",
                     "--in", "2"]) == 0
    assert cli_main(["--data-dir", str(data), "add", "--name", "坏", "--prompt", "x",
                     "--every", "1"]) == 2                     # 少于 5 分钟被拒
    store = SchedulerStore(data / "scheduler")
    jobs = store.list_jobs()
    assert len(jobs) == 1 and jobs[0].trigger.kind == "once" and jobs[0].created_by == "cli"
    nxt = datetime.fromisoformat(jobs[0].next_fire_at)
    assert timedelta(minutes=1) < nxt - datetime.now(nxt.tzinfo) <= timedelta(minutes=2, seconds=5)
    assert cli_main(["--data-dir", str(data), "disable", jobs[0].id]) == 0
    assert SchedulerStore(data / "scheduler").get(jobs[0].id).enabled is False
    assert cli_main(["--data-dir", str(data), "list"]) == 0
    assert cli_main(["--data-dir", str(data), "remove", jobs[0].id]) == 0
    assert SchedulerStore(data / "scheduler").list_jobs() == []


# ---------------- S4：界面需要的状态 ----------------

def test_state_carries_enabled_flag(tmp_path):
    async def main():
        host, _sessions, sent, _calls = make_host(tmp_path)
        await host.push_state()
        state = [m for m in sent if m["type"] == "schedule.state"][-1]
        assert state["enabled"] is True and state["jobs"][0]["schedule_text"]
    asyncio.run(main())


def test_disabled_message_is_read_only_and_does_not_create_dirs(tmp_path):
    empty = disabled_message(tmp_path / "nothing", "schedule.list", {})
    assert empty == {"v": 1, "type": "schedule.state", "enabled": False, "jobs": [],
                     "session_id": "", "session_name": SCHEDULER_SESSION_NAME}
    assert not (tmp_path / "nothing" / "scheduler").exists()

    data = tmp_path / "data"
    assert cli_main(["--data-dir", str(data), "add", "--name", "命令行建的", "--prompt", "p",
                     "--daily", "09:00"]) == 0
    state = disabled_message(data, "schedule.state", {})
    assert state["enabled"] is False and [j["name"] for j in state["jobs"]] == ["命令行建的"]
    assert state["jobs"][0]["schedule_text"] == "每天 09:00" and state["jobs"][0]["running"] is False
    runs = disabled_message(data, "schedule.runs", {"job_id": state["jobs"][0]["id"]})
    assert runs["type"] == "schedule.runs" and runs["runs"] == []


def test_save_rejects_unknown_id_and_ignores_stats_on_create(tmp_path):
    async def main():
        host, _sessions, sent, _calls = make_host(tmp_path)
        await host.handle("schedule.save", {"job": {"id": "ghost", "name": "x", "prompt": "p",
                                                    "trigger": {"kind": "daily", "time": "09:00"}}})
        ack = [m for m in sent if m["type"] == "schedule.ack"][-1]
        assert ack["ok"] is False and "找不到任务" in ack["message"]
        await host.handle("schedule.save", {"job": {"name": "新", "prompt": "p", "created_by": "preset",
                                                    "consecutive_failures": 9, "last_state": "ok",
                                                    "trigger": {"kind": "daily", "time": "09:00"}}})
        job = next(j for j in host.store.list_jobs() if j.name == "新")
        assert job.created_by == "user" and job.consecutive_failures == 0 and job.last_state == ""
    asyncio.run(main())
