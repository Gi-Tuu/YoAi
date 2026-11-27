"""S3：让智能体在对话里管理定时任务（对齐 OpenClaw 的 cron 工具，按 YoAi 权限模型拆分）。

OpenClaw 给智能体一个 ``cron`` 工具（add / list / run / remove …）。YoAi 的权限白名单
按**工具名**判断是否自动放行，所以拆成 6 个工具：

| 工具 | 权限 |
|---|---|
| ``schedule_list`` / ``schedule_runs`` | 只读，进 smart 白名单，无人值守也可用 |
| ``schedule_create`` / ``schedule_cancel`` / ``schedule_toggle`` / ``schedule_run_now`` | **每次弹窗确认**；无人值守**永不放行**（定时任务不能自我繁殖） |

与 OpenClaw 的差异（有意为之）：
- 一次性时间不带时区时按**本地时间**理解（OpenClaw 按 UTC）——对话里"明天 9 点"指本地；
- 额外提供 ``in_minutes``（"20 分钟后"），不让模型自己算时间；
- 只会建在专用「⏰ 定时任务」会话里跑的任务（相当于 OpenClaw 的 isolated），
  所以工具说明要求模型把任务内容写成**不依赖当前对话**的完整指令。

工具函数都是同步的、线程安全的：对任务表的修改走 ``SchedulerStore`` 的锁；
"立即运行"只入队，由事件循环里的 tick 执行（最多约 30 秒后开始）。
"""

import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable

from yoai.scheduler.models import (
    MIN_INTERVAL_S,
    SCHEDULER_SESSION_NAME,
    Job,
    SchedulerError,
    Trigger,
    from_iso,
)
from yoai.scheduler.triggers import describe, local_tz, resolve_tz

MAX_AGENT_JOBS = 20          # 智能体最多建 20 个任务（防止模型反复重试刷出一堆）
_WEEK_CN = "一二三四五六日"
_WEEK_ALIASES = {"工作日": [0, 1, 2, 3, 4], "周末": [5, 6], "每天": list(range(7))}

READONLY_SCHEDULE_TOOLS = ("schedule_list", "schedule_runs")
WRITE_SCHEDULE_TOOLS = ("schedule_create", "schedule_cancel", "schedule_toggle", "schedule_run_now")


# ---------------- 解析辅助 ----------------

def parse_weekdays(text: str) -> list[int]:
    """"0,3" / "1-5" / "一,三,五" / "周一、周四" / "工作日" / "周末" → 0=周一 … 6=周日。"""
    raw = (text or "").strip()
    if raw in _WEEK_ALIASES:
        return list(_WEEK_ALIASES[raw])
    days: set[int] = set()
    for part in re.split(r"[,，、\s]+", raw):
        part = part.strip().replace("星期", "").replace("周", "").replace("礼拜", "")
        if not part:
            continue
        part = part.replace("天", "日")
        if re.fullmatch(r"[0-6]-[0-6]", part):
            a, b = (int(x) for x in part.split("-"))
            if a > b:
                raise SchedulerError(f"星期范围写反了：{part}")
            days.update(range(a, b + 1))
        elif re.fullmatch(r"[0-6]", part):
            days.add(int(part))
        elif len(part) == 1 and part in _WEEK_CN:
            days.add(_WEEK_CN.index(part))
        elif re.fullmatch(r"[一二三四五六日]-[一二三四五六日]", part):
            a, b = (_WEEK_CN.index(x) for x in part.split("-"))
            days.update(range(a, b + 1))
        else:
            raise SchedulerError(f"看不懂的星期：{part}（用 0=周一 … 6=周日，或 一、三、五）")
    if not days:
        raise SchedulerError("每周任务至少要有一天")
    return sorted(days)


def parse_local_time(text: str) -> datetime:
    """ISO 时间；不带时区按**本地**。支持 "2026-11-28 09:00" 与 "2026-11-28T09:00:00+08:00"。"""
    raw = (text or "").strip().replace("/", "-")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SchedulerError(f"时间格式不对：{text!r}，应为 2026-11-28 09:00") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt


def _fmt(dt_text: str, tz_name: str = "") -> str:
    dt = from_iso(dt_text)
    if dt is None:
        return "—"
    local = dt.astimezone(resolve_tz(tz_name))
    return f"{local:%Y-%m-%d %H:%M}（周{_WEEK_CN[local.weekday()]}）"


def build_trigger(*, when: str = "", in_minutes: float = 0, every_minutes: float = 0,
                  daily_at: str = "", weekly: str = "", cron: str = "",
                  now: Callable[[], datetime] | None = None) -> Trigger:
    given = [bool(when), bool(in_minutes), bool(every_minutes), bool(daily_at),
             bool(weekly), bool(cron)]
    if sum(given) != 1:
        raise SchedulerError(
            "时间要且只能指定一种：when（一次性时间）/ in_minutes（N 分钟后）/ "
            "every_minutes（每 N 分钟）/ daily_at（每天 HH:MM）/ weekly（星期@HH:MM）/ cron")
    clock = now or (lambda: datetime.now(local_tz()))
    if when:
        return Trigger(kind="once", at=parse_local_time(when).isoformat())
    if in_minutes:
        if in_minutes <= 0 or in_minutes > 60 * 24 * 366:
            raise SchedulerError("in_minutes 应在 0 到一年之间")
        at = clock() + timedelta(minutes=float(in_minutes))
        return Trigger(kind="once", at=at.isoformat(timespec="seconds"))
    if every_minutes:
        if every_minutes * 60 < MIN_INTERVAL_S:
            raise SchedulerError(f"间隔不能小于 {MIN_INTERVAL_S // 60} 分钟")
        return Trigger(kind="interval", every_s=int(round(every_minutes * 60)))
    if daily_at:
        return Trigger(kind="daily", time=daily_at.strip())
    if weekly:
        days, sep, at = weekly.partition("@")
        if not sep:
            raise SchedulerError("weekly 格式：星期@HH:MM，例如 \"一,三,五@08:30\" 或 \"工作日@09:00\"")
        return Trigger(kind="weekly", weekdays=parse_weekdays(days), time=at.strip())
    return Trigger(kind="cron", expr=cron.strip())


# ---------------- 工具 ----------------

def _job_view(job: Job, running: bool = False) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "schedule": describe(job.trigger),
        "next_run": _fmt(job.next_fire_at, job.trigger.tz) if job.enabled else "—",
        "last_state": job.last_state or "—",
        "running": running,
        "prompt": job.prompt if len(job.prompt) <= 120 else job.prompt[:120] + "…",
        **({"disabled_reason": job.disabled_reason} if job.disabled_reason else {}),
        **({"active_hours": job.active_hours} if job.active_hours else {}),
    }


def schedule_tool_functions(host: Any) -> dict[str, Callable[..., str]]:
    """返回 {工具名: 函数}。函数签名与 docstring 即模型看到的 schema 与说明。"""
    engine = host.engine
    store = host.store

    def _changed() -> None:
        notify = getattr(host, "notify_changed", None)
        if notify is not None:
            notify()

    def _dump(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=1)

    def schedule_list() -> str:
        """列出全部定时任务：名称、何时运行、下次运行时间、上次结果、是否开启。
        用户问"我有哪些定时任务 / 提醒""明天几点会提醒我"时先调用它；
        取消、暂停或立即运行某个任务前，也先用它查到准确的任务 id。"""
        jobs = [_job_view(j, engine.is_running(j.id)) for j in store.list_jobs()]
        return _dump({"count": len(jobs), "result_session": SCHEDULER_SESSION_NAME, "jobs": jobs})

    def schedule_runs(job_id: str = "", limit: int = 5) -> str:
        """查看定时任务最近的运行记录（时间、状态、结果摘要、被拒绝的工具）。
        job_id 留空查全部任务；limit 为条数（1–20）。用户问"上次提醒跑了没有 / 结果是什么"时用。"""
        limit = max(1, min(20, int(limit or 5)))
        runs = store.runs(job_id.strip(), limit=limit)
        return _dump([{
            "job": r.job_name or r.job_id, "time": _fmt(r.started_at), "state": r.state,
            "quiet": r.quiet, "reason": r.reason, "summary": r.summary[:300],
            **({"denied_tools": r.denied_tools} if r.denied_tools else {}),
        } for r in runs])

    def schedule_create(name: str, prompt: str, when: str = "", in_minutes: float = 0,
                        every_minutes: float = 0, daily_at: str = "", weekly: str = "",
                        cron: str = "", active_hours: str = "") -> str:
        """创建一个定时任务：prompt 必须写成不依赖当前对话的完整指令；到点后自动执行，结果放在「⏰ 定时任务」会话。

        时间**只填一种**：
        - when：一次性，本地时间，如 "2026-11-28 09:00"（先用 now 工具确认今天日期）；
        - in_minutes：N 分钟后执行一次，如 20；
        - every_minutes：每 N 分钟一次（至少 5）；
        - daily_at：每天 "HH:MM"；
        - weekly："星期@HH:MM"，星期写 一,三,五 / 1-5 / 工作日 / 周末（0=周一 … 6=周日）；
        - cron：5 段 cron 表达式（需要 croniter）。
        active_hours 可选，如 "08:00-23:00"，时间窗外不执行。

        prompt 要写成**不依赖当前对话的完整指令**——执行时是一个新的会话，看不到现在的聊天。
        例如写"提醒用户：今晚 8 点和男朋友吃饭"，而不是"提醒我那件事"。
        定时运行时没人在场，只能用只读和记忆类工具；需要执行命令、改文件、删除记忆的事做不了。"""
        agent_jobs = [j for j in store.list_jobs() if j.created_by == "agent"]
        if len(agent_jobs) >= MAX_AGENT_JOBS:
            return f"已经有 {len(agent_jobs)} 个由对话创建的任务，超过上限 {MAX_AGENT_JOBS}，请先取消一些。"
        try:
            trigger = build_trigger(when=when, in_minutes=in_minutes, every_minutes=every_minutes,
                                    daily_at=daily_at, weekly=weekly, cron=cron)
            for existing in store.list_jobs():       # 模型重试时别重复建
                if (existing.enabled and existing.name == name.strip()
                        and existing.prompt == prompt.strip()
                        and existing.trigger.to_dict() == trigger.to_dict()):
                    return (f"已有完全相同的任务「{existing.name}」（id {existing.id}），没有重复创建。"
                            f"下次运行：{_fmt(existing.next_fire_at)}")
            job = engine.add_job(Job(name=name.strip(), prompt=prompt.strip(), trigger=trigger,
                                     active_hours=active_hours.strip(), created_by="agent"))
        except SchedulerError as exc:
            return f"没有创建：{exc}"
        _changed()
        return (f"已创建定时任务「{job.name}」（id {job.id}）：{describe(job.trigger)}，"
                f"下次运行 {_fmt(job.next_fire_at, job.trigger.tz)}。"
                f"结果会出现在「{SCHEDULER_SESSION_NAME}」会话。")

    def schedule_cancel(job_id: str) -> str:
        """永久删除一个定时任务（运行记录保留）。job_id 用 schedule_list 查到的准确 id；
        只想暂停的话用 schedule_toggle。"""
        job = store.get(job_id.strip())
        if job is None:
            return f"找不到任务 {job_id}（先用 schedule_list 查准确 id）"
        engine.cancel_run(job.id)
        engine.remove_job(job.id)
        _changed()
        return f"已删除定时任务「{job.name}」。"

    def schedule_toggle(job_id: str, enabled: bool) -> str:
        """暂停（enabled=false）或恢复（enabled=true）一个定时任务，不删除它。"""
        try:
            job = engine.set_enabled(job_id.strip(), bool(enabled))
        except SchedulerError as exc:
            return f"没有修改：{exc}"
        _changed()
        if job.enabled:
            return f"已恢复「{job.name}」，下次运行 {_fmt(job.next_fire_at, job.trigger.tz)}。"
        return f"已暂停「{job.name}」。"

    def schedule_run_now(job_id: str) -> str:
        """让一个定时任务马上额外运行一次（不改变它原定的时间）。
        约 30 秒内开始，结果出现在「⏰ 定时任务」会话；用户正在对话时会等对话结束再跑。"""
        try:
            engine.request_run(job_id.strip())
        except SchedulerError as exc:
            return f"没有运行：{exc}"
        job = store.get(job_id.strip())
        _changed()
        return f"已安排「{job.name if job else job_id}」立即运行，结果会出现在「{SCHEDULER_SESSION_NAME}」会话。"

    return {
        "schedule_list": schedule_list,
        "schedule_runs": schedule_runs,
        "schedule_create": schedule_create,
        "schedule_cancel": schedule_cancel,
        "schedule_toggle": schedule_toggle,
        "schedule_run_now": schedule_run_now,
    }


def schedule_tool_specs(host: Any) -> list[Any]:
    """用 Core 的 build_spec 把上面的函数变成 ToolSpec（schema 来自签名与 docstring）。"""
    from yai_core import build_spec
    return [build_spec(fn) for fn in schedule_tool_functions(host).values()]
