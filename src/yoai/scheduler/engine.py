"""SchedulerEngine：决定"什么时候跑什么"，不关心怎么跑。

真正执行通过注入的 ``runner(job, record, prompt) -> RunResult`` 完成；
时钟、"用户是否正在用 agent"、目标列表、通知出口全部可注入——
单测用假时钟 + 假 runner 即可毫秒级验证跨天 / 错过 / 重叠 / 中断等逻辑。

规则全部来自 docs/SCHEDULER-PLAN.md 第 5、7、13 节：
- tick 默认 30s；到点的任务启动一次，然后从"现在"算下一次（错过多次也只补一次）
- 同一任务上一次没结束 → 本次记 skipped
- idle_only 任务在用户任务进行中 → 等待，最多 busy_wait_s（默认 10 分钟），超时记 skipped
- active_hours 时间窗外不执行，直接排到下一次（手动运行不受限）
- 检查清单显式为空 → 安静跳过（OpenClaw skipIfScratchEmpty）
- 单次运行超时 timeout_s；失败后按 30s/1m/5m/15m/60m 推迟下一次（成功复位），
  连续失败 5 次自动停用；一次性任务不重试
- 智能体只回复 NO_REPLY → 成功但安静，不打扰用户
- 进程退出时正在跑的运行**不写终态**，下次启动由 startup() 补记 interrupted
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from yoai.scheduler.models import (
    BACKOFF_STEPS_S,
    MAX_CONSECUTIVE_FAILURES,
    MISFIRE_SKIP,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_OK,
    RUN_RUNNING,
    RUN_SKIPPED,
    RUN_TIMEOUT,
    Job,
    RunRecord,
    RunResult,
    SchedulerError,
    from_iso,
    is_quiet,
    now_utc,
    to_iso,
)
from yoai.scheduler.store import SchedulerStore
from yoai.scheduler.triggers import describe, in_active_hours, next_fire_time

log = logging.getLogger("yoai.scheduler")

Runner = Callable[[Job, RunRecord, str], Awaitable[RunResult]]
Notify = Callable[[str, dict[str, Any]], Any]

STARTED, WAITING, SKIPPED = "started", "waiting", "skipped"
_UNRESTRICTED_REASONS = ("manual", "retry_interrupted")   # 不受时间窗限制


def render_prompt(prompt: str, variables: dict[str, Any] | None) -> str:
    """只替换已知占位符 {name}，不用 str.format（prompt 里的 JSON 花括号不会炸）。"""
    out = prompt
    for key, value in (variables or {}).items():
        out = out.replace("{" + key + "}", str(value))
    return out


class SchedulerEngine:
    def __init__(
        self,
        store: SchedulerStore,
        runner: Runner,
        *,
        clock: Callable[[], datetime] | None = None,
        is_busy: Callable[[], bool] | None = None,
        goals_provider: Callable[[], list[dict[str, Any]]] | None = None,
        notify: Notify | None = None,
        tick_s: float = 30,
        busy_wait_s: float = 600,
        misfire_grace_s: float = 90,
        stale_check_s: float = 3600,
    ) -> None:
        self.store = store
        self.runner = runner
        self.clock = clock or now_utc
        self.is_busy = is_busy
        self.goals_provider = goals_provider
        self.notify = notify
        self.tick_s = tick_s
        self.busy_wait_s = busy_wait_s
        self.misfire_grace_s = misfire_grace_s
        self.stale_check_s = stale_check_s

        self._running: dict[str, asyncio.Task] = {}          # job_id -> 运行任务
        self._busy_since: dict[str, datetime] = {}           # job_id -> 开始等待用户任务的时间
        self._pending: dict[str, tuple[str, dict[str, Any]]] = {}  # 事件/手动触发但需等待的
        self._misfire_ids: set[str] = set()
        self._user_cancelled: set[str] = set()
        self._last_stale_check: datetime | None = None
        self._loop_task: asyncio.Task | None = None

    # ================= 任务管理 =================
    def _advance(self, job: Job, after: datetime) -> None:
        """从 after 起算下一次；一次性任务跑过即停用。"""
        if job.trigger.kind == "event":
            job.next_fire_at = ""
            return
        nxt = next_fire_time(job.trigger, after)
        job.next_fire_at = to_iso(nxt)
        if nxt is None and job.trigger.kind == "once":
            job.enabled = False
            job.disabled_reason = job.disabled_reason or "一次性任务已执行"

    def add_job(self, job: Job) -> Job:
        job.validate()
        if self.store.get(job.id) is not None:
            raise SchedulerError(f"任务 {job.id} 已存在")
        self._schedule_fresh(job)
        return self.store.save(job)

    def update_job(self, job: Job) -> Job:
        job.validate()
        if self.store.get(job.id) is None:
            raise SchedulerError(f"找不到任务 {job.id}")
        self._schedule_fresh(job)
        return self.store.save(job)

    def _schedule_fresh(self, job: Job) -> None:
        if job.trigger.kind == "event":
            job.next_fire_at = ""
            return
        nxt = next_fire_time(job.trigger, self.clock())
        if nxt is None:
            raise SchedulerError("设定的时间已经过去了")
        job.next_fire_at = to_iso(nxt)

    def remove_job(self, job_id: str) -> bool:
        self._pending.pop(job_id, None)
        self._misfire_ids.discard(job_id)
        return self.store.delete(job_id)

    def set_enabled(self, job_id: str, enabled: bool) -> Job:
        job = self.store.get(job_id)
        if job is None:
            raise SchedulerError(f"找不到任务 {job_id}")
        if enabled:
            self._schedule_fresh(job)
            job.consecutive_failures = 0
            job.disabled_reason = ""
        else:
            self._pending.pop(job_id, None)
        job.enabled = enabled
        return self.store.save(job)

    def is_running(self, job_id: str) -> bool:
        task = self._running.get(job_id)
        return task is not None and not task.done()

    def any_running(self) -> bool:
        """有任何定时运行正在进行（含已删除任务的残留运行）。"""
        return any(not t.done() for t in self._running.values())

    def state(self) -> list[dict[str, Any]]:
        """给界面用的任务列表快照。"""
        out = []
        for job in self.store.list_jobs():
            item = job.to_dict()
            item["schedule_text"] = describe(job.trigger)
            item["running"] = self.is_running(job.id)
            item["waiting"] = job.id in self._pending or job.id in self._busy_since
            out.append(item)
        return out

    # ================= 生命周期 =================
    async def startup(self) -> list[RunRecord]:
        """启动时调用一次：补记中断、处理错过、发 app_started 事件。"""
        now = self.clock()
        interrupted = self.store.mark_interrupted()
        for rec in interrupted:
            await self._emit_notify("run_interrupted", rec.to_dict())
            job = self.store.get(rec.job_id)
            if (job and job.enabled and job.on_interrupt == "retry_once"
                    and rec.reason != "retry_interrupted"):
                self._pending[job.id] = ("retry_interrupted", {})

        for job in self.store.list_jobs():
            if not job.enabled or job.trigger.kind == "event":
                continue
            nxt = from_iso(job.next_fire_at)
            if nxt is None:
                self._advance(job, now)
                self.store.save(job)
                continue
            if nxt < now - timedelta(seconds=self.misfire_grace_s):
                if job.misfire == MISFIRE_SKIP:
                    self._advance(job, now)
                    self.store.save(job)
                else:
                    self._misfire_ids.add(job.id)   # 下一次 tick 补跑一次

        await self.emit("app_started")
        return interrupted

    def start(self) -> asyncio.Task:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self.run_forever(), name="yoai-scheduler")
        return self._loop_task

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - 调度循环永不因单次异常退出
                log.exception("scheduler tick failed")
            await asyncio.sleep(self.tick_s)

    async def shutdown(self) -> None:
        """停止循环并取消运行中的任务。被取消的运行不写终态 → 下次启动记为 interrupted。"""
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        tasks = [t for t in self._running.values() if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_idle(self) -> None:
        """测试 / 手动场景：等所有运行结束。"""
        tasks = [t for t in self._running.values() if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ================= 触发 =================
    async def tick(self) -> list[str]:
        now = self.clock()
        launched: list[str] = []
        try:
            self.store.refresh()            # 外部（命令行工具）改过 jobs.json 就重载
        except Exception:  # noqa: BLE001
            log.exception("scheduler store refresh failed")

        for job_id, (reason, variables) in list(self._pending.items()):
            job = self.store.get(job_id)
            if job is None or not job.enabled:
                self._pending.pop(job_id, None)
                continue
            status, run_id = await self._fire(job, reason, variables)
            if status != WAITING:
                self._pending.pop(job_id, None)
            if run_id:
                launched.append(run_id)

        for job in self.store.list_jobs():
            if not job.enabled or job.trigger.kind == "event" or job.id in self._pending:
                continue
            nxt = from_iso(job.next_fire_at)
            if nxt is None or nxt > now:
                continue
            reason = "misfire" if job.id in self._misfire_ids else "schedule"
            _status, run_id = await self._fire(job, reason, {})
            if run_id:
                launched.append(run_id)

        launched.extend(await self._check_stale_goals(now))
        return launched

    async def run_now(self, job_id: str) -> str:
        """手动立即运行（不改变原定的下次时间）。返回 run_id；需等待时返回空串。"""
        job = self.store.get(job_id)
        if job is None:
            raise SchedulerError(f"找不到任务 {job_id}")
        status, run_id = await self._fire(job, "manual", {}, advance=False)
        if status == WAITING:
            self._pending[job_id] = ("manual", {})
        return run_id

    async def emit(self, event_name: str, **payload: Any) -> list[str]:
        """外部事件入口：app_started / goal_created / goal_status_changed。"""
        launched: list[str] = []
        for job in self.store.list_jobs():
            trig = job.trigger
            if not job.enabled or trig.kind != "event" or trig.event != event_name:
                continue
            # params 作等值过滤，例如 {"status": "done"} 只在目标完成时触发
            if any(payload.get(k) != v for k, v in trig.params.items()):
                continue
            reason = f"event:{event_name}"
            status, run_id = await self._fire(job, reason, payload)
            if status == WAITING:
                self._pending[job.id] = (reason, dict(payload))
            if run_id:
                launched.append(run_id)
        return launched

    def cancel_run(self, job_id: str) -> bool:
        task = self._running.get(job_id)
        if task is None or task.done():
            return False
        self._user_cancelled.add(job_id)
        task.cancel()
        return True

    async def _check_stale_goals(self, now: datetime) -> list[str]:
        if self.goals_provider is None:
            return []
        if (self._last_stale_check is not None
                and (now - self._last_stale_check).total_seconds() < self.stale_check_s):
            return []
        self._last_stale_check = now
        jobs = [j for j in self.store.list_jobs()
                if j.enabled and j.trigger.kind == "event" and j.trigger.event == "goal_stale"]
        if not jobs:
            return []
        try:
            goals = list(self.goals_provider())
        except Exception:  # noqa: BLE001
            log.exception("goals_provider failed")
            return []

        launched: list[str] = []
        for job in jobs:
            if self.is_running(job.id) or job.id in self._pending:
                continue
            days = float(job.trigger.params.get("days", 3))
            fired: dict[str, str] = job.state.setdefault("stale_fired", {})
            live_ids = {str(g.get("id", "")) for g in goals}
            for gid in list(fired):            # 目标被删了就清掉去重记录
                if gid not in live_ids:
                    fired.pop(gid)
            for goal in goals:
                if goal.get("status") not in ("pending", "active"):
                    continue
                gid, updated_raw = str(goal.get("id", "")), str(goal.get("updated_at", ""))
                updated = from_iso(updated_raw)
                if not gid or updated is None:
                    continue
                idle = now - updated
                if idle < timedelta(days=days) or fired.get(gid) == updated_raw:
                    continue                    # 没到天数，或这一段停滞已经提醒过
                variables = {"goal_id": gid, "goal_title": goal.get("title", ""),
                             "days_idle": idle.days}
                status, run_id = await self._fire(job, "event:goal_stale", variables)
                if status == STARTED:
                    fired[gid] = updated_raw
                    self.store.save(job)
                    launched.append(run_id)
                break                            # 每个任务每轮只提醒一个目标
        return launched

    # ================= 执行 =================
    async def _fire(self, job: Job, reason: str, variables: dict[str, Any],
                    *, advance: bool = True) -> tuple[str, str]:
        now = self.clock()

        if self.is_running(job.id):
            self._busy_since.pop(job.id, None)
            await self._record_skip(job, reason, "上一次运行仍未结束")
            if advance:
                self._advance(job, now)
                self.store.save(job)
            return SKIPPED, ""

        if (reason not in _UNRESTRICTED_REASONS and job.active_hours
                and not in_active_hours(job.active_hours, now, job.trigger.tz)):
            self._busy_since.pop(job.id, None)
            self._misfire_ids.discard(job.id)
            if advance:                     # 时间窗外：安静地排到下一次，不记运行
                self._advance(job, now)
                self.store.save(job)
            return SKIPPED, ""

        if job.idle_only and self.is_busy is not None and self.is_busy():
            since = self._busy_since.setdefault(job.id, now)
            if (now - since).total_seconds() < self.busy_wait_s:
                return WAITING, ""
            self._busy_since.pop(job.id, None)
            await self._record_skip(job, reason, "等待用户任务结束超过时限")
            if advance:
                self._advance(job, now)
                self.store.save(job)
            return SKIPPED, ""

        self._busy_since.pop(job.id, None)
        self._misfire_ids.discard(job.id)

        if job.scratch is not None and not job.scratch.strip() and job.skip_if_scratch_empty:
            await self._record_skip(job, reason, "检查清单为空，跳过", quiet=True)
            if advance:
                self._advance(job, now)
                self.store.save(job)
            return SKIPPED, ""

        record = RunRecord(job_id=job.id, reason=reason, job_name=job.name,
                           started_at=to_iso(now))
        self.store.append_run(record)
        job.last_run_id = record.run_id
        job.last_state = RUN_RUNNING
        if advance:
            self._advance(job, now)
        self.store.save(job)
        await self._emit_notify("run_started", record.to_dict())

        prompt = render_prompt(job.prompt, variables)
        if job.scratch and job.scratch.strip():
            prompt = f"{prompt}\n\n【检查清单】\n{job.scratch.strip()}"
        task = asyncio.create_task(self._execute(job.id, record, prompt),
                                   name=f"yoai-schedule-{job.id}")
        self._running[job.id] = task
        return STARTED, record.run_id

    async def _record_skip(self, job: Job, reason: str, why: str, *, quiet: bool = False) -> None:
        now = to_iso(self.clock())
        rec = RunRecord(job_id=job.id, reason=reason, job_name=job.name, state=RUN_SKIPPED,
                        started_at=now, finished_at=now, summary=why, quiet=quiet)
        self.store.append_run(rec)
        await self._emit_notify("run_finished", rec.to_dict())

    async def _execute(self, job_id: str, record: RunRecord, prompt: str) -> None:
        job = self.store.get(job_id)
        timeout = job.timeout_s if job else 600
        try:
            try:
                result = await asyncio.wait_for(self.runner(job, record, prompt), timeout=timeout)
                record.state = RUN_OK if result.ok else RUN_FAILED
                record.summary = (result.summary or "")[:2000]
                record.quiet = bool(result.ok and is_quiet(record.summary))
                record.denied_tools = list(result.denied_tools)
                record.evidence_id = result.evidence_id
            except asyncio.CancelledError:
                if job_id in self._user_cancelled:
                    self._user_cancelled.discard(job_id)
                    record.state = RUN_INTERRUPTED
                    record.summary = "已被手动取消"
                    record.finished_at = to_iso(self.clock())
                    self.store.append_run(record)
                    await self._emit_notify("run_finished", record.to_dict())
                raise                      # 进程退出的取消：不写终态，下次启动补记
            except TimeoutError:
                record.state = RUN_TIMEOUT
                record.summary = f"超过 {timeout} 秒仍未完成，已停止"
            except Exception as exc:  # noqa: BLE001 - 坏任务不能拖垮调度器
                record.state = RUN_FAILED
                record.summary = f"{type(exc).__name__}: {exc}"[:2000]

            record.finished_at = to_iso(self.clock())
            self.store.append_run(record)
            await self._after_run(job_id, record)
        finally:
            if self._running.get(job_id) is asyncio.current_task():
                self._running.pop(job_id, None)

    async def _after_run(self, job_id: str, record: RunRecord) -> None:
        job = self.store.get(job_id)
        disabled = False
        if job is not None:
            job.last_state = record.state
            if record.state == RUN_OK:
                job.consecutive_failures = 0
            elif record.state in (RUN_FAILED, RUN_TIMEOUT):
                job.consecutive_failures += 1
                if job.consecutive_failures >= MAX_CONSECUTIVE_FAILURES and job.enabled:
                    job.enabled = False
                    job.disabled_reason = f"连续失败 {job.consecutive_failures} 次，已自动停用"
                    disabled = True
                elif job.enabled and job.trigger.kind not in ("once", "event"):
                    self._apply_backoff(job, record)
            self.store.save(job)
        await self._emit_notify("run_finished", record.to_dict())
        if disabled and job is not None:
            await self._emit_notify("job_disabled", job.to_dict())

    def _apply_backoff(self, job: Job, record: RunRecord) -> None:
        """失败后推迟下一次：max(原定下一次, 结束时间 + 退避)。只会推迟，不会提前。"""
        step = BACKOFF_STEPS_S[min(job.consecutive_failures, len(BACKOFF_STEPS_S)) - 1]
        finished = from_iso(record.finished_at) or self.clock()
        delayed = finished + timedelta(seconds=step)
        planned = from_iso(job.next_fire_at)
        if planned is None or planned < delayed:
            job.next_fire_at = to_iso(delayed)

    async def _emit_notify(self, kind: str, payload: dict[str, Any]) -> None:
        if self.notify is None:
            return
        try:
            res = self.notify(kind, payload)
            if inspect.isawaitable(res):
                await res
        except Exception:  # noqa: BLE001 - 通知失败不影响调度
            log.exception("scheduler notify failed")
