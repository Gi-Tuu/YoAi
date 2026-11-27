"""S3 对话工具测试：schedule_* 工具的解析、权限、与引擎 / 桥的配合。

前半部分用假会话、不依赖 Core；最后两项需要 Core（build_spec / YoAiAgent），找不到时跳过。
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.scheduler.host import SchedulerHost  # noqa: E402
from yoai.scheduler.models import SchedulerError  # noqa: E402
from yoai.scheduler.policy import UnattendedGate  # noqa: E402
from yoai.scheduler.tools import (  # noqa: E402
    MAX_AGENT_JOBS, READONLY_SCHEDULE_TOOLS, WRITE_SCHEDULE_TOOLS,
    build_trigger, parse_weekdays, schedule_tool_functions,
)

CN = timezone(timedelta(hours=8))


# ---------------- 假件（与 test_scheduler_host 同构，独立一份避免测试间导入） ----------------

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
        self.core = Obj(policy=Obj(mode="auto", allowed=set()), executor=Obj(policy=None))
        self.prompts: list[str] = []
        self.goals = Obj(list_goals=lambda: [])

    async def astream(self, prompt):
        self.prompts.append(prompt)
        yield Ev("done", {"final_text": "提醒已发出", "status": "ok"})


class FakeSessions:
    def __init__(self) -> None:
        self._s: dict[str, Obj] = {}
        self._agents: dict[str, FakeAgent] = {}
        self._current = None
        self._counter = 0
        self.create("新会话")

    def create(self, name=""):
        self._counter += 1
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

    def agent_for(self, sid=None):
        return self._agents.setdefault(sid or self._current, FakeAgent())

    def touch(self, sid=None, *, delta=1):
        pass


def make(tmp_path):
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    host = SchedulerHost(
        tmp_path, FakeSessions(), send, is_busy=lambda: False,
        channel_factory=lambda cb: cb,
        policy_factory=lambda allowed: Obj(mode="auto", allowed=set(allowed)),
        clean_text=lambda s: s, tick_s=3600, provision=False,
    )
    return host, schedule_tool_functions(host), sent


# ---------------- 解析 ----------------

def test_parse_weekdays_accepts_common_forms():
    assert parse_weekdays("0,3") == [0, 3]
    assert parse_weekdays("1-5") == [1, 2, 3, 4, 5]
    assert parse_weekdays("一,三,五") == [0, 2, 4]
    assert parse_weekdays("周一、周四") == [0, 3]
    assert parse_weekdays("星期日") == [6]
    assert parse_weekdays("一-五") == [0, 1, 2, 3, 4]
    assert parse_weekdays("工作日") == [0, 1, 2, 3, 4]
    assert parse_weekdays("周末") == [5, 6]
    for bad in ("", "7", "周八", "5-1"):
        with pytest.raises(SchedulerError):
            parse_weekdays(bad)


def test_build_trigger_requires_exactly_one_time():
    with pytest.raises(SchedulerError):
        build_trigger()
    with pytest.raises(SchedulerError):
        build_trigger(daily_at="09:00", in_minutes=5)


def test_build_trigger_kinds():
    fixed = datetime(2026, 11, 27, 14, 0, tzinfo=CN)
    t = build_trigger(in_minutes=20, now=lambda: fixed)
    assert t.kind == "once" and datetime.fromisoformat(t.at) == fixed + timedelta(minutes=20)

    t = build_trigger(when="2026-11-28 09:00")
    at = datetime.fromisoformat(t.at)
    assert at.tzinfo is not None and (at.hour, at.minute) == (9, 0)    # 不带时区 = 本地 09:00

    assert build_trigger(every_minutes=30).every_s == 1800
    with pytest.raises(SchedulerError):
        build_trigger(every_minutes=2)                                  # 少于 5 分钟

    t = build_trigger(weekly="工作日@08:30")
    assert (t.kind, t.weekdays, t.time) == ("weekly", [0, 1, 2, 3, 4], "08:30")
    with pytest.raises(SchedulerError):
        build_trigger(weekly="工作日")                                   # 缺 @HH:MM

    assert build_trigger(daily_at=" 21:00 ").time == "21:00"
    assert build_trigger(cron="0 9 * * *").kind == "cron"


# ---------------- 工具 ----------------

def test_create_list_and_dedupe(tmp_path):
    host, tools, _sent = make(tmp_path)
    msg = tools["schedule_create"](name="晚饭提醒", prompt="提醒用户：今晚 8 点和男朋友吃饭",
                                   in_minutes=30)
    assert msg.startswith("已创建") and "⏰ 定时任务" in msg
    job = host.store.list_jobs()[0]
    assert job.created_by == "agent" and job.trigger.kind == "once"

    again = tools["schedule_create"](name="晚饭提醒", prompt="提醒用户：今晚 8 点和男朋友吃饭",
                                     when=job.trigger.at)
    assert "没有重复创建" in again and len(host.store.list_jobs()) == 1

    listed = json.loads(tools["schedule_list"]())
    assert listed["count"] == 1 and listed["jobs"][0]["id"] == job.id
    assert listed["jobs"][0]["schedule"].startswith("一次")


def test_create_errors_are_returned_not_raised(tmp_path):
    host, tools, _sent = make(tmp_path)
    assert tools["schedule_create"](name="x", prompt="p").startswith("没有创建")
    assert tools["schedule_create"](name="x", prompt="p", daily_at="9点").startswith("没有创建")
    assert tools["schedule_create"](name="", prompt="p", daily_at="09:00").startswith("没有创建")
    assert tools["schedule_create"](name="x", prompt="p", when="2020-01-01 09:00").startswith("没有创建")
    assert host.store.list_jobs() == []


def test_agent_job_cap(tmp_path):
    host, tools, _sent = make(tmp_path)
    for i in range(MAX_AGENT_JOBS):
        assert tools["schedule_create"](name=f"任务{i}", prompt=f"p{i}", daily_at="09:00").startswith("已创建")
    assert "超过上限" in tools["schedule_create"](name="多余", prompt="p", daily_at="09:00")


def test_toggle_cancel_and_unknown_ids(tmp_path):
    host, tools, _sent = make(tmp_path)
    tools["schedule_create"](name="早间", prompt="列出目标", daily_at="09:00")
    job = host.store.list_jobs()[0]
    assert tools["schedule_toggle"](job_id=job.id, enabled=False).startswith("已暂停")
    assert host.store.get(job.id).enabled is False
    assert tools["schedule_toggle"](job_id=job.id, enabled=True).startswith("已恢复")
    assert tools["schedule_cancel"](job_id=job.id).startswith("已删除")
    assert host.store.get(job.id) is None
    assert "找不到" in tools["schedule_cancel"](job_id="nope")
    assert tools["schedule_toggle"](job_id="nope", enabled=True).startswith("没有修改")
    assert tools["schedule_run_now"](job_id="nope").startswith("没有运行")


def test_run_now_is_queued_then_runs_without_moving_schedule(tmp_path):
    async def main():
        host, tools, _sent = make(tmp_path)
        tools["schedule_create"](name="早间", prompt="列出目标", daily_at="09:00")
        job = host.store.list_jobs()[0]
        planned = job.next_fire_at
        assert tools["schedule_run_now"](job_id=job.id).startswith("已安排")
        await host.engine.tick()
        await host.engine.wait_idle()
        rec = host.store.runs(job.id)[0]
        assert rec.reason == "manual" and rec.state == "ok"
        assert host.store.get(job.id).next_fire_at == planned
        runs = json.loads(tools["schedule_runs"](job_id=job.id))
        assert runs[0]["state"] == "ok" and runs[0]["summary"] == "提醒已发出"
    asyncio.run(main())


def test_tool_changes_push_state_after_start(tmp_path):
    async def main():
        host, tools, sent = make(tmp_path)
        tools["schedule_create"](name="启动前", prompt="p", daily_at="09:00")   # 未启动：不推送也不报错
        await host.start()
        before = sum(1 for m in sent if m["type"] == "schedule.state")
        tools["schedule_create"](name="启动后", prompt="p", daily_at="10:00")
        await asyncio.sleep(0.01)
        after = sum(1 for m in sent if m["type"] == "schedule.state")
        assert after == before + 1
        await host.shutdown()
    asyncio.run(main())


# ---------------- 权限 ----------------

def test_unattended_runs_cannot_manage_schedules():
    gate = UnattendedGate(extra=list(WRITE_SCHEDULE_TOOLS))      # 就算用户勾了也不行
    for name in READONLY_SCHEDULE_TOOLS:
        assert gate.decide(name) is True
    for name in WRITE_SCHEDULE_TOOLS:
        assert gate.decide(name) is False


# ---------------- 需要 Core ----------------

def test_specs_build_with_core(tmp_path):
    pytest.importorskip("yai_core")
    host, _tools, _sent = make(tmp_path)
    specs = host.tool_specs()
    names = {s.name for s in specs}
    assert names == set(READONLY_SCHEDULE_TOOLS) | set(WRITE_SCHEDULE_TOOLS)
    create = next(s for s in specs if s.name == "schedule_create")
    assert "不依赖当前对话" in (create.description or "")


def test_agent_registers_extra_tools(tmp_path):
    pytest.importorskip("yai_core")
    from yoai.agent import YoAiAgent
    from yoai.demo_model import DemoModel
    host, _tools, _sent = make(tmp_path / "sched")
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "agent",
                      extra_tool_specs=host.tool_specs)
    names = set(agent.list_tools())
    assert {"schedule_list", "schedule_create"} <= names

    def broken():
        raise RuntimeError("坏了")
    agent2 = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "agent2", extra_tool_specs=broken)
    assert "schedule_list" not in set(agent2.list_tools())     # 坏的额外工具不影响构造
    assert "remember_fact" in set(agent2.list_tools())
