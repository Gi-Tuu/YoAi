"""Scheduler S1 单测：全部离线、假时钟、假 runner，不依赖 Core。

覆盖 docs/SCHEDULER-PLAN.md 第 10 节测试清单 + S1.1（对齐 OpenClaw）新增行为。
cron 相关用例需要 croniter；未安装时自动跳过。
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

from yoai.scheduler import (  # noqa: E402
    Job, RunResult, SchedulerEngine, SchedulerError, SchedulerStore, Trigger,
    UnattendedGate, allowed_set, describe, next_fire_time, render_prompt,
)
from yoai.scheduler.models import RUN_RUNNING, RunRecord, is_quiet  # noqa: E402
from yoai.scheduler.presets import heartbeat_job, morning_review_job  # noqa: E402
from yoai.scheduler.triggers import in_active_hours  # noqa: E402

try:
    import croniter as _croniter  # noqa: F401
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False
needs_croniter = pytest.mark.skipif(not HAS_CRONITER, reason="需要 croniter")

CN = timezone(timedelta(hours=8))


def from_iso_(text):
    return datetime.fromisoformat(text)


def t(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=CN)


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


class FakeRunner:
    def __init__(self, ok=True, delay=0.0, raises=None, summary="完成") -> None:
        self.calls: list[tuple[str, str]] = []
        self.ok, self.delay, self.raises, self.summary = ok, delay, raises, summary
        self.gate: asyncio.Event | None = None

    async def __call__(self, job, record, prompt):
        self.calls.append((job.id, prompt))
        if self.gate is not None:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise self.raises
        return RunResult(ok=self.ok, summary=self.summary)


def daily(time_="09:00"):
    return Trigger(kind="daily", time=time_, tz="+08:00")


def make(tmp_path, clock, runner=None, **kw):
    store = SchedulerStore(tmp_path / "scheduler")
    eng = SchedulerEngine(store, runner or FakeRunner(), clock=clock, **kw)
    return store, eng


# ---------------- 触发时间（纯函数） ----------------

def test_daily_before_and_after_time():
    trig = daily()
    assert next_fire_time(trig, t(2026, 11, 27, 8, 59)) == t(2026, 11, 27, 9, 0)
    assert next_fire_time(trig, t(2026, 11, 27, 9, 0)) == t(2026, 11, 28, 9, 0)   # 严格晚于
    assert next_fire_time(trig, t(2026, 11, 27, 9, 1)) == t(2026, 11, 28, 9, 0)


def test_daily_crosses_month_and_year():
    trig = daily("08:30")
    assert next_fire_time(trig, t(2026, 11, 30, 23, 0)) == t(2026, 12, 1, 8, 30)
    assert next_fire_time(trig, t(2026, 12, 31, 23, 0)) == t(2027, 1, 1, 8, 30)


def test_weekly_multiple_days():
    trig = Trigger(kind="weekly", weekdays=[0, 3], time="20:00", tz="+08:00")  # 周一、周四
    # 2026-11-27 是周五 → 下一次是 11-30 周一
    assert next_fire_time(trig, t(2026, 11, 27, 12)) == t(2026, 11, 30, 20, 0)
    # 周一 20:00 之后 → 周四
    assert next_fire_time(trig, t(2026, 11, 30, 20, 1)) == t(2026, 12, 3, 20, 0)


def test_timezone_is_respected_regardless_of_input_zone():
    trig = daily("09:00")
    after_utc = datetime(2026, 11, 27, 0, 30, tzinfo=timezone.utc)   # = 北京 08:30
    assert next_fire_time(trig, after_utc) == t(2026, 11, 27, 9, 0)


def test_once_and_interval():
    once = Trigger(kind="once", at=t(2026, 11, 28, 15).isoformat())
    assert next_fire_time(once, t(2026, 11, 28, 14)) == t(2026, 11, 28, 15)
    assert next_fire_time(once, t(2026, 11, 28, 15)) is None
    every = Trigger(kind="interval", every_s=3600)
    assert next_fire_time(every, t(2026, 11, 27, 10)) == t(2026, 11, 27, 11)


def test_validation_messages():
    with pytest.raises(SchedulerError):
        Trigger(kind="interval", every_s=60).validate()          # 低于 5 分钟
    with pytest.raises(SchedulerError):
        Trigger(kind="daily", time="9:00").validate()             # 格式
    with pytest.raises(SchedulerError):
        Trigger(kind="weekly", weekdays=[], time="09:00").validate()
    with pytest.raises(SchedulerError):
        Trigger(kind="event", event="file_changed").validate()    # v1 不支持
    with pytest.raises(SchedulerError):
        Job(name="", trigger=daily(), prompt="x").validate()


def test_describe_is_chinese():
    assert describe(daily()) == "每天 09:00"
    assert describe(Trigger(kind="interval", every_s=7200)) == "每 2 小时"
    assert "周一" in describe(Trigger(kind="weekly", weekdays=[0], time="09:00"))


def test_render_prompt_keeps_json_braces():
    out = render_prompt('目标「{goal_title}」停滞，按 {"a": 1} 格式输出', {"goal_title": "写论文"})
    assert out == '目标「写论文」停滞，按 {"a": 1} 格式输出'


# ---------------- 引擎：正常触发 ----------------

def test_job_fires_once_at_time_then_moves_to_next_day(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 8, 50))
        runner = FakeRunner()
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="早间回顾", trigger=daily(), prompt="列出目标"))
        assert job.next_fire_at == t(2026, 11, 27, 9).isoformat()

        assert await eng.tick() == []                 # 还没到
        clock.advance(minutes=10)
        launched = await eng.tick()
        await eng.wait_idle()
        assert len(launched) == 1 and runner.calls == [(job.id, "列出目标")]
        assert store.get(job.id).next_fire_at == t(2026, 11, 28, 9).isoformat()
        assert store.runs(job.id)[0].state == "ok"

        assert await eng.tick() == []                 # 同一分钟不重复跑
    asyncio.run(main())


def test_once_job_disables_itself_after_run(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        store, eng = make(tmp_path, clock)
        job = eng.add_job(Job(name="交作业提醒",
                              trigger=Trigger(kind="once", at=t(2026, 11, 27, 10, 5).isoformat()),
                              prompt="提醒我交作业"))
        clock.advance(minutes=5)
        await eng.tick()
        await eng.wait_idle()
        j = store.get(job.id)
        assert j.enabled is False and j.next_fire_at == ""
    asyncio.run(main())


def test_once_in_the_past_is_rejected(tmp_path):
    clock = Clock(t(2026, 11, 27, 10))
    _store, eng = make(tmp_path, clock)
    with pytest.raises(SchedulerError):
        eng.add_job(Job(name="x", trigger=Trigger(kind="once", at=t(2026, 11, 26).isoformat()),
                        prompt="x"))


# ---------------- 错过（应用关闭期间） ----------------

def _closed_for_three_days(tmp_path, misfire):
    async def main():
        clock = Clock(t(2026, 11, 27, 8))
        runner = FakeRunner()
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="每日", trigger=daily(), prompt="p", misfire=misfire))

        # 应用关闭 3 天，重新打开时是 11-30 12:00
        clock.now = t(2026, 11, 30, 12)
        store2 = SchedulerStore(tmp_path / "scheduler")
        eng2 = SchedulerEngine(store2, runner, clock=clock)
        await eng2.startup()
        await eng2.tick()
        await eng2.wait_idle()
        await eng2.tick()                              # 再 tick 也不会继续补
        await eng2.wait_idle()
        return runner, store2.get(job.id), store2
    return asyncio.run(main())


def test_misfire_run_once_catches_up_only_once(tmp_path):
    runner, job, store = _closed_for_three_days(tmp_path, "run_once")
    assert len(runner.calls) == 1
    assert store.runs(job.id)[0].reason == "misfire"
    assert job.next_fire_at == t(2026, 12, 1, 9).isoformat()


def test_misfire_skip_does_not_catch_up(tmp_path):
    runner, job, _store = _closed_for_three_days(tmp_path, "skip")
    assert runner.calls == []
    assert job.next_fire_at == t(2026, 12, 1, 9).isoformat()


# ---------------- 重叠 / 用户正忙 ----------------

def test_overlap_is_skipped_not_queued(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner()
        runner.gate = asyncio.Event()                   # 让第一次一直卡住
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="轮询", trigger=Trigger(kind="interval", every_s=300), prompt="p"))
        clock.advance(minutes=5)
        await eng.tick()
        await asyncio.sleep(0)
        clock.advance(minutes=5)
        await eng.tick()                                # 第一次还没结束
        states = sorted(r.state for r in store.runs(job.id))
        assert states == ["running", "skipped"]
        runner.gate.set()
        await eng.wait_idle()
        assert len(runner.calls) == 1
    asyncio.run(main())


def test_waits_while_user_busy_then_runs(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 8, 59))
        busy = {"v": True}
        runner = FakeRunner()
        store, eng = make(tmp_path, clock, runner, is_busy=lambda: busy["v"])
        job = eng.add_job(Job(name="早间", trigger=daily(), prompt="p"))
        clock.advance(minutes=1)
        assert await eng.tick() == []                   # 用户在用，先等
        assert eng.state()[0]["waiting"] is True
        busy["v"] = False
        clock.advance(minutes=1)
        assert len(await eng.tick()) == 1
        await eng.wait_idle()
        assert store.runs(job.id)[0].state == "ok"
    asyncio.run(main())


def test_busy_too_long_records_skip(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 8, 59))
        runner = FakeRunner()
        store, eng = make(tmp_path, clock, runner, is_busy=lambda: True, busy_wait_s=600)
        job = eng.add_job(Job(name="早间", trigger=daily(), prompt="p"))
        clock.advance(minutes=1)
        await eng.tick()
        clock.advance(minutes=11)
        await eng.tick()
        assert runner.calls == []
        assert store.runs(job.id)[0].state == "skipped"
        assert store.get(job.id).next_fire_at == t(2026, 11, 28, 9).isoformat()
    asyncio.run(main())


# ---------------- 失败 / 超时 / 自动停用 ----------------

def test_five_failures_auto_disable(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        events = []
        runner = FakeRunner(raises=RuntimeError("网关 500"))
        store, eng = make(tmp_path, clock, runner, notify=lambda k, p: events.append(k))
        job = eng.add_job(Job(name="坏任务", trigger=Trigger(kind="interval", every_s=300), prompt="p"))
        for _ in range(5):
            clock.advance(hours=2)                   # 跳过退避期
            await eng.tick()
            await eng.wait_idle()
        j = store.get(job.id)
        assert j.enabled is False and "连续失败 5 次" in j.disabled_reason
        assert "job_disabled" in events
        assert "RuntimeError: 网关 500" in store.runs(job.id)[0].summary
        clock.advance(hours=2)
        assert await eng.tick() == []                    # 停用后不再跑
    asyncio.run(main())


def test_failure_backoff_steps_match_openclaw(tmp_path):
    """连续失败后下一次至少推迟 30s/1m/5m/15m/60m（只推迟，不提前）。"""
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner(ok=False)
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="x", trigger=Trigger(kind="interval", every_s=300), prompt="p"))
        expected_gap = [300, 300, 300, 900]           # max(5 分钟间隔, 退避)
        for gap in expected_gap:
            clock.now = from_iso_(store.get(job.id).next_fire_at)
            await eng.tick()
            await eng.wait_idle()
            nxt = from_iso_(store.get(job.id).next_fire_at)
            assert (nxt - clock.now).total_seconds() == gap
        runner.ok = True                               # 成功后复位
        clock.now = from_iso_(store.get(job.id).next_fire_at)
        await eng.tick()
        await eng.wait_idle()
        assert store.get(job.id).consecutive_failures == 0
        assert (from_iso_(store.get(job.id).next_fire_at) - clock.now).total_seconds() == 300
    asyncio.run(main())


def test_once_job_does_not_retry_after_failure(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner(ok=False)
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="x", trigger=Trigger(kind="once", at=t(2026, 11, 27, 10, 5).isoformat()),
                              prompt="p"))
        clock.advance(minutes=5)
        await eng.tick()
        await eng.wait_idle()
        clock.advance(hours=3)
        await eng.tick()
        assert len(runner.calls) == 1 and store.get(job.id).enabled is False
    asyncio.run(main())


def test_success_resets_failure_counter(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner(ok=False)
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="x", trigger=Trigger(kind="interval", every_s=300), prompt="p"))
        for ok in (False, False, True):
            runner.ok = ok
            clock.advance(minutes=5)
            await eng.tick()
            await eng.wait_idle()
        assert store.get(job.id).consecutive_failures == 0
        assert store.get(job.id).enabled is True
    asyncio.run(main())


def test_timeout_is_recorded(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner(delay=5)
        store, eng = make(tmp_path, clock, runner)
        job = Job(name="慢", trigger=Trigger(kind="interval", every_s=300), prompt="p", timeout_s=30)
        eng.add_job(job)
        store.get(job.id).timeout_s = 0.05             # 绕过校验下限，只为测试快
        clock.advance(minutes=5)
        await eng.tick()
        await eng.wait_idle()
        assert store.runs(job.id)[0].state == "timeout"
    asyncio.run(main())


# ---------------- 中断恢复 ----------------

def test_interrupted_run_is_marked_on_next_startup(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner()
        runner.gate = asyncio.Event()
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="长任务", trigger=Trigger(kind="interval", every_s=300),
                              prompt="p", on_interrupt="retry_once"))
        clock.advance(minutes=5)
        await eng.tick()
        await asyncio.sleep(0)
        await eng.shutdown()                            # 模拟应用被关掉
        assert store.runs(job.id)[0].state == RUN_RUNNING   # 没写终态

        runner2 = FakeRunner()
        store2 = SchedulerStore(tmp_path / "scheduler")
        eng2 = SchedulerEngine(store2, runner2, clock=clock)
        interrupted = await eng2.startup()
        assert [r.job_id for r in interrupted] == [job.id]
        await eng2.tick()                               # retry_once → 自动重跑一次
        await eng2.wait_idle()
        reasons = [r.reason for r in store2.runs(job.id)]
        assert "retry_interrupted" in reasons
        assert any(r.state == "interrupted" for r in store2.runs(job.id, limit=0))
        assert len(runner2.calls) == 1
    asyncio.run(main())


def test_concurrent_triggers_do_not_double_run(tmp_path):
    """回归：通知回调会让出事件循环；旧实现在登记运行之前就 await 通知，
    两个同时到达的触发（tick / 界面命令 / 对话工具）会把同一任务跑两次。"""
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner()
        runner.gate = asyncio.Event()

        async def notify(kind, payload):
            await asyncio.sleep(0)

        store, eng = make(tmp_path, clock, runner, notify=notify)
        job = eng.add_job(Job(name="x", trigger=daily(), prompt="p"))
        await asyncio.gather(eng.run_now(job.id), eng.run_now(job.id))
        await asyncio.sleep(0)
        runner.gate.set()
        await eng.wait_idle()
        assert len(runner.calls) == 1
        assert sorted(r.state for r in store.runs(job.id, limit=0)) == ["ok", "skipped"]
    asyncio.run(main())


def test_manual_cancel_is_recorded(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner()
        runner.gate = asyncio.Event()
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="x", trigger=daily(), prompt="p"))
        await eng.run_now(job.id)
        await asyncio.sleep(0)
        assert eng.cancel_run(job.id) is True
        await eng.wait_idle()
        rec = store.runs(job.id)[0]
        assert rec.state == "interrupted" and rec.summary == "已被手动取消"
        assert store.get(job.id).consecutive_failures == 0   # 手动取消不算失败
    asyncio.run(main())


def test_run_now_keeps_original_schedule(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 7))
        store, eng = make(tmp_path, clock)
        job = eng.add_job(Job(name="x", trigger=daily(), prompt="p"))
        before = store.get(job.id).next_fire_at
        assert await eng.run_now(job.id)
        await eng.wait_idle()
        assert store.get(job.id).next_fire_at == before
        assert store.runs(job.id)[0].reason == "manual"
    asyncio.run(main())


# ---------------- 事件触发 ----------------

def test_app_started_event(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner()
        store, eng = make(tmp_path, clock, runner)
        eng.add_job(Job(name="启动问候", trigger=Trigger(kind="event", event="app_started"),
                        prompt="今天先做什么？"))
        await eng.startup()
        await eng.wait_idle()
        assert runner.calls and runner.calls[0][1] == "今天先做什么？"
    asyncio.run(main())


def test_goal_status_event_with_filter(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner()
        _store, eng = make(tmp_path, clock, runner)
        eng.add_job(Job(name="完成庆祝",
                        trigger=Trigger(kind="event", event="goal_status_changed",
                                        params={"status": "done"}),
                        prompt="目标「{goal_title}」完成了，总结一下"))
        assert await eng.emit("goal_status_changed", status="active", goal_title="A") == []
        await eng.emit("goal_status_changed", status="done", goal_title="写论文")
        await eng.wait_idle()
        assert runner.calls[0][1] == "目标「写论文」完成了，总结一下"
    asyncio.run(main())


def test_goal_stale_fires_once_per_idle_period(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        goals = [{"id": "g1", "title": "学中文", "status": "active",
                  "updated_at": t(2026, 11, 23).isoformat()}]
        runner = FakeRunner()
        store, eng = make(tmp_path, clock, runner, goals_provider=lambda: goals, stale_check_s=0)
        eng.add_job(Job(name="停滞提醒",
                        trigger=Trigger(kind="event", event="goal_stale", params={"days": 3}),
                        prompt="「{goal_title}」已经 {days_idle} 天没动了"))
        await eng.tick()
        await eng.wait_idle()
        assert runner.calls[0][1] == "「学中文」已经 4 天没动了"

        clock.advance(hours=2)
        await eng.tick()
        await eng.wait_idle()
        assert len(runner.calls) == 1                    # 同一段停滞不重复提醒

        goals[0]["updated_at"] = t(2026, 11, 27, 11).isoformat()   # 用户更新了目标
        clock.now = t(2026, 12, 1, 12)                              # 又停了 4 天
        await eng.tick()
        await eng.wait_idle()
        assert len(runner.calls) == 2
    asyncio.run(main())


def test_done_goals_are_not_stale(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        goals = [{"id": "g1", "title": "x", "status": "done",
                  "updated_at": t(2026, 11, 1).isoformat()}]
        runner = FakeRunner()
        _store, eng = make(tmp_path, clock, runner, goals_provider=lambda: goals, stale_check_s=0)
        eng.add_job(Job(name="停滞", trigger=Trigger(kind="event", event="goal_stale"), prompt="p"))
        await eng.tick()
        assert runner.calls == []
    asyncio.run(main())


# ---------------- 持久化 ----------------

def test_jobs_persist_across_instances(tmp_path):
    clock = Clock(t(2026, 11, 27, 8))
    store, eng = make(tmp_path, clock)
    job = eng.add_job(Job(name="早间", trigger=daily(), prompt="p", allowed_tools=["web_search"]))
    again = SchedulerStore(tmp_path / "scheduler").get(job.id)
    assert again is not None and again.trigger.time == "09:00"
    assert again.allowed_tools == ["web_search"]


def test_corrupt_jobs_file_is_isolated(tmp_path):
    root = tmp_path / "scheduler"
    root.mkdir()
    (root / "jobs.json").write_text("{坏掉的 json", encoding="utf-8")
    store = SchedulerStore(root)
    assert store.list_jobs() == []
    assert (root / "jobs.json.corrupt").exists()


def test_half_written_run_line_is_ignored(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler")
    store.append_run(RunRecord(job_id="j1", reason="schedule", state="ok"))
    with store.run_file("j1").open("a", encoding="utf-8") as fh:
        fh.write('{"run_id": "sch-x", "job_id": "j1", "sta')   # 断电写了一半
    assert len(store.runs("j1")) == 1


def test_runs_file_is_valid_jsonl(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 8, 59))
        store, eng = make(tmp_path, clock)
        job = eng.add_job(Job(name="x", trigger=daily(), prompt="p"))
        clock.advance(minutes=1)
        await eng.tick()
        await eng.wait_idle()
        lines = store.run_file(job.id).read_text(encoding="utf-8").splitlines()
        assert [json.loads(x)["state"] for x in lines] == ["running", "ok"]
    asyncio.run(main())


# ---------------- 无人值守权限 ----------------

def test_unattended_gate_defaults():
    gate = UnattendedGate()
    assert gate.decide("list_goals") is True
    assert gate.decide("remember_fact") is True         # 拍板：允许记忆类写
    assert gate.decide("shell_run") is False
    assert gate.decide("proj_write") is False
    assert gate.decide("mcp__github__create_issue") is False
    assert gate.denied == ["shell_run", "proj_write", "mcp__github__create_issue"]


def test_never_allowed_cannot_be_unlocked():
    allowed = allowed_set(["shell_run", "forget_fact", "schedule_create", "custom_tool"])
    assert "custom_tool" in allowed
    assert not {"shell_run", "forget_fact", "schedule_create"} & allowed


# ================= S1.1：对齐 OpenClaw =================

@needs_croniter
def test_cron_expression_next_fire():
    trig = Trigger(kind="cron", expr="30 9 * * 1-5", tz="+08:00")   # 工作日 09:30
    trig.validate()
    # 2026-11-27 周五 10:00 → 下周一 11-30 09:30
    assert next_fire_time(trig, t(2026, 11, 27, 10)) == t(2026, 11, 30, 9, 30)
    assert describe(trig) == "cron 30 9 * * 1-5"


@needs_croniter
def test_cron_invalid_expression_rejected():
    with pytest.raises(SchedulerError):
        Trigger(kind="cron", expr="61 * * * *").validate()


def test_cron_without_library_gives_clear_message():
    if HAS_CRONITER:
        return
    with pytest.raises(SchedulerError):
        Trigger(kind="cron", expr="0 9 * * *").validate()


def test_active_hours_window():
    assert in_active_hours("08:00-23:00", t(2026, 11, 27, 8), "+08:00")
    assert not in_active_hours("08:00-23:00", t(2026, 11, 27, 23, 30), "+08:00")
    assert in_active_hours("22:00-06:00", t(2026, 11, 27, 2), "+08:00")      # 跨夜
    assert not in_active_hours("22:00-06:00", t(2026, 11, 27, 12), "+08:00")
    assert in_active_hours("", t(2026, 11, 27, 3))
    with pytest.raises(SchedulerError):
        Job(name="x", trigger=daily(), prompt="p", active_hours="8-23").validate()


def test_outside_active_hours_is_rescheduled_quietly(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 23, 0))
        runner = FakeRunner()
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="心跳", trigger=Trigger(kind="interval", every_s=1800, tz="+08:00"),
                              prompt="p", active_hours="08:00-23:00"))
        clock.advance(minutes=30)                      # 23:30，窗外
        await eng.tick()
        assert runner.calls == [] and store.runs(job.id) == []
        assert store.get(job.id).next_fire_at == t(2026, 11, 28, 0, 0).isoformat()
        assert await eng.run_now(job.id)               # 手动运行不受时间窗限制
        await eng.wait_idle()
        assert len(runner.calls) == 1
    asyncio.run(main())


def test_idle_only_false_runs_even_when_busy(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 8, 59))
        runner = FakeRunner()
        _store, eng = make(tmp_path, clock, runner, is_busy=lambda: True)
        eng.add_job(Job(name="急", trigger=daily(), prompt="p", idle_only=False))
        clock.advance(minutes=1)
        assert len(await eng.tick()) == 1
        await eng.wait_idle()
    asyncio.run(main())


def test_empty_scratch_skips_quietly_and_scratch_goes_into_prompt(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 10))
        runner = FakeRunner()
        events = []
        store, eng = make(tmp_path, clock, runner, notify=lambda k, p: events.append((k, p)))
        empty = eng.add_job(Job(name="空清单", trigger=Trigger(kind="interval", every_s=300),
                                prompt="检查", scratch=""))
        full = eng.add_job(Job(name="有清单", trigger=Trigger(kind="interval", every_s=300),
                               prompt="检查", scratch="- 看看目标"))
        clock.advance(minutes=5)
        await eng.tick()
        await eng.wait_idle()
        assert store.runs(empty.id)[0].state == "skipped" and store.runs(empty.id)[0].quiet
        assert runner.calls == [(full.id, "检查\n\n【检查清单】\n- 看看目标")]
    asyncio.run(main())


def test_no_reply_marks_run_quiet(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 8, 59))
        runner = FakeRunner(summary="NO_REPLY")
        store, eng = make(tmp_path, clock, runner)
        job = eng.add_job(Job(name="心跳", trigger=daily(), prompt="p"))
        clock.advance(minutes=1)
        await eng.tick()
        await eng.wait_idle()
        rec = store.runs(job.id)[0]
        assert rec.state == "ok" and rec.quiet is True
    asyncio.run(main())
    assert is_quiet(" HEARTBEAT_OK ") and not is_quiet("目标「学中文」停滞 4 天")


def test_run_log_is_pruned(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler", max_bytes=2000, keep_lines=5)
    for i in range(60):
        store.append_run(RunRecord(job_id="j1", reason="schedule", state="ok", summary=f"第{i}次"))
    lines = store.run_file("j1").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 30 and store.run_file("j1").stat().st_size <= 2000 + 400
    assert store.runs("j1", limit=1)[0].summary == "第59次"


def test_external_edit_is_reloaded(tmp_path):
    async def main():
        clock = Clock(t(2026, 11, 27, 8))
        store, eng = make(tmp_path, clock)
        # 模拟命令行工具在应用运行时添加任务：另一个 store 实例写同一目录
        other = SchedulerStore(tmp_path / "scheduler")
        added = morning_review_job()
        added.trigger.tz = "+08:00"
        added.next_fire_at = t(2026, 11, 27, 9).isoformat()
        other.save(added)
        await eng.tick()
        assert store.get(added.id) is not None
    asyncio.run(main())


def test_presets_are_valid_and_heartbeat_is_off_by_default():
    hb = heartbeat_job()
    hb.validate()
    morning_review_job().validate()
    assert hb.enabled is False and hb.idle_only and hb.active_hours == "08:00-23:00"
    assert hb.trigger.every_s == 1800 and "NO_REPLY" in hb.prompt
