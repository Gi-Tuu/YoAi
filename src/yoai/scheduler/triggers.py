"""触发时间计算：纯函数，注入时间即可单测（不读系统时钟）。

约定：``next_fire_time(trigger, after)`` 返回**严格晚于** ``after`` 的下一次触发时间；
没有下一次（一次性任务已过、事件触发）返回 None。

时区：Windows 上 ``zoneinfo`` 需要 tzdata 包，未安装时 ``ZoneInfo("Asia/Shanghai")``
会抛异常——因此解析失败一律回退到系统本地时区，而不是让调度器崩溃。
固定偏移（"+08:00"）与 UTC 不依赖 tzdata，单测与 CI 用它们保证结果与机器无关。

cron 表达式交给成熟库 croniter（pallets-eco 维护）解析；日与星期两个字段同时给出时
按 OR 语义（标准 cron 行为，OpenClaw 文档同样如此）。
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone, tzinfo

from yoai.scheduler.models import Trigger, from_iso

_OFFSET_RE = re.compile(r"^([+-])([01]\d|2[0-3]):?([0-5]\d)$")


def local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def resolve_tz(name: str) -> tzinfo:
    """支持：空/local = 本地；UTC；固定偏移 "+08:00"；IANA 名（需 tzdata，失败回退本地）。"""
    if not name or name.lower() == "local":
        return local_tz()
    if name.upper() in ("UTC", "Z"):
        return timezone.utc
    m = _OFFSET_RE.match(name)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - 无 tzdata / 名字错：回退本地，不崩
        return local_tz()


def _parse_hhmm(text: str) -> time:
    hh, mm = text.split(":")
    return time(int(hh), int(mm))


def next_fire_time(trigger: Trigger, after: datetime) -> datetime | None:
    if after.tzinfo is None:
        raise ValueError("after 必须带时区")

    kind = trigger.kind
    if kind == "once":
        at = from_iso(trigger.at)
        return at if at is not None and at > after else None

    if kind == "interval":
        every = max(int(trigger.every_s), 1)
        return after + timedelta(seconds=every)

    if kind in ("daily", "weekly"):
        tz = resolve_tz(trigger.tz)
        local_after = after.astimezone(tz)
        at = _parse_hhmm(trigger.time)
        allowed = set(range(7)) if kind == "daily" else set(trigger.weekdays)
        if not allowed:
            return None
        # 最多看 8 天：覆盖"今天已过 + 一整周"
        for offset in range(8):
            day = local_after.date() + timedelta(days=offset)
            if day.weekday() not in allowed:
                continue
            candidate = datetime.combine(day, at, tzinfo=tz)
            if candidate > local_after:
                return candidate
        return None

    if kind == "cron":
        from croniter import croniter
        tz = resolve_tz(trigger.tz)
        local_after = after.astimezone(tz)
        nxt = croniter(trigger.expr.strip(), local_after).get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=tz)
        return nxt if nxt > after else None

    # event：不按时间触发
    return None


# ---------------- 执行时间窗（OpenClaw activeHours） ----------------

def _window(text: str) -> tuple[int, int]:
    start, end = text.split("-")
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    return sh * 60 + sm, eh * 60 + em


def in_active_hours(window: str, dt: datetime, tz_name: str = "") -> bool:
    """window 为空 = 不限。支持跨夜："22:00-06:00"。"""
    if not window:
        return True
    start, end = _window(window)
    local = dt.astimezone(resolve_tz(tz_name))
    minute = local.hour * 60 + local.minute
    if start == end:
        return True
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def describe(trigger: Trigger) -> str:
    """给界面和 agent 用的中文描述。"""
    names = "一二三四五六日"
    if trigger.kind == "once":
        at = from_iso(trigger.at)
        return f"一次 · {at.astimezone(resolve_tz(trigger.tz)):%Y-%m-%d %H:%M}" if at else "一次"
    if trigger.kind == "interval":
        mins = int(trigger.every_s) // 60
        return f"每 {mins // 60} 小时" if mins % 60 == 0 and mins >= 60 else f"每 {mins} 分钟"
    if trigger.kind == "daily":
        return f"每天 {trigger.time}"
    if trigger.kind == "weekly":
        days = "、".join("周" + names[d] for d in trigger.weekdays)
        return f"每周 {days} {trigger.time}"
    if trigger.kind == "cron":
        return f"cron {trigger.expr.strip()}"
    if trigger.kind == "event":
        label = {
            "app_started": "应用启动时",
            "goal_created": "新建目标时",
            "goal_status_changed": "目标状态变化时",
            "goal_stale": f"目标 {trigger.params.get('days', 3)} 天未更新时",
        }
        return label.get(trigger.event, trigger.event)
    return trigger.kind
