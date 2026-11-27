"""调度器数据结构：Trigger / Job / RunRecord。

纯数据 + 校验，不做 I/O。时间一律存带偏移的 ISO 字符串（便于 JSON 与人读）。
设计见 docs/SCHEDULER-PLAN.md 第 4、5、13 节。

S1.1（2026-11-27）对齐 OpenClaw automations：
- cron 表达式（解析交给成熟库 croniter，不自写）
- 失败指数退避 30s→1m→5m→15m→60m，成功复位；一次性任务不重试
- active_hours 执行时间窗、idle_only 让路前台任务、scratch 检查清单
- 安静结果：回复 NO_REPLY 表示"没有需要报告的"，不打扰用户
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

# ---- 常量（方案第 5 节定死的规则）----
TRIGGER_KINDS = ("once", "interval", "daily", "weekly", "cron", "event")
EVENT_NAMES = ("app_started", "goal_created", "goal_status_changed", "goal_stale")
MISFIRE_RUN_ONCE = "run_once"   # 拍板（2026-11-27）：默认补跑一次
MISFIRE_SKIP = "skip"
MISFIRE_POLICIES = (MISFIRE_RUN_ONCE, MISFIRE_SKIP)
ON_INTERRUPT = ("notify", "retry_once")

MIN_INTERVAL_S = 300            # interval 下限 5 分钟，防止烧额度
DEFAULT_TIMEOUT_S = 600         # 整个任务的硬上限（不是单次模型调用）
# 对齐 OpenClaw：连续失败后按 30s / 1m / 5m / 15m / 60m 推迟下一次，成功后复位
BACKOFF_STEPS_S = (30, 60, 300, 900, 3600)
# YoAi 额外的额度保护：连续失败 5 次自动停用（OpenClaw 同样有 auto-disabled 状态）
MAX_CONSECUTIVE_FAILURES = 5
DEFAULT_SESSION = "scheduler"   # 拍板（2026-11-27）：结果进专用「⏰ 定时任务」会话
SCHEDULER_SESSION_NAME = "⏰ 定时任务"
# 安静结果标记：智能体只回复这个，表示这次检查没有需要用户关注的内容
QUIET_TOKENS = ("NO_REPLY", "HEARTBEAT_OK")

# 运行状态
RUN_RUNNING = "running"
RUN_OK = "ok"
RUN_FAILED = "failed"
RUN_TIMEOUT = "timeout"
RUN_INTERRUPTED = "interrupted"
RUN_SKIPPED = "skipped"
RUN_STATES = (RUN_RUNNING, RUN_OK, RUN_FAILED, RUN_TIMEOUT, RUN_INTERRUPTED, RUN_SKIPPED)
TERMINAL_STATES = tuple(s for s in RUN_STATES if s != RUN_RUNNING)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_WINDOW_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]|24):([0-5]\d)$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt is not None else ""


def from_iso(text: str) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:          # 不接受无时区时间：按 UTC 理解（与 OpenClaw 一致）
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def is_quiet(text: str) -> bool:
    return text.strip().strip("。.").upper() in QUIET_TOKENS


class SchedulerError(ValueError):
    """任务定义不合法（给用户看的中文原因）。"""


def _cron_valid(expr: str) -> bool:
    try:
        from croniter import croniter
    except ImportError as exc:
        raise SchedulerError("cron 表达式需要安装 croniter：pip install croniter") from exc
    return bool(croniter.is_valid(expr))


@dataclass
class Trigger:
    kind: str
    at: str = ""                       # once：ISO 时间
    every_s: int = 0                   # interval：秒
    time: str = ""                     # daily/weekly："HH:MM"
    weekdays: list[int] = field(default_factory=list)  # weekly：0=周一 … 6=周日
    expr: str = ""                     # cron：5 段（可 6 段带秒）表达式
    event: str = ""                    # event：事件名
    params: dict[str, Any] = field(default_factory=dict)  # event 过滤条件，如 {"days": 3}
    tz: str = ""                       # 空 = 系统本地时区

    def validate(self) -> None:
        if self.kind not in TRIGGER_KINDS:
            raise SchedulerError(f"未知触发类型：{self.kind}")
        if self.kind == "once":
            if from_iso(self.at) is None:
                raise SchedulerError("一次性任务需要合法的时间（ISO 格式）")
        elif self.kind == "interval":
            if int(self.every_s) < MIN_INTERVAL_S:
                raise SchedulerError(f"间隔不能小于 {MIN_INTERVAL_S // 60} 分钟")
        elif self.kind in ("daily", "weekly"):
            if not _TIME_RE.match(self.time or ""):
                raise SchedulerError("时间格式应为 HH:MM，例如 09:00")
            if self.kind == "weekly":
                if not self.weekdays or any(d not in range(7) for d in self.weekdays):
                    raise SchedulerError("每周任务需要至少一个星期几（0=周一 … 6=周日）")
        elif self.kind == "cron":
            if not self.expr.strip() or not _cron_valid(self.expr.strip()):
                raise SchedulerError(f"cron 表达式不合法：{self.expr!r}")
        elif self.kind == "event":
            if self.event not in EVENT_NAMES:
                raise SchedulerError(f"未知事件：{self.event}")
            if self.event == "goal_stale":
                days = self.params.get("days", 3)
                if not isinstance(days, (int, float)) or days < 1:
                    raise SchedulerError("目标停滞天数至少为 1")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Trigger:
        return cls(
            kind=str(raw.get("kind", "")),
            at=str(raw.get("at", "")),
            every_s=int(raw.get("every_s", 0) or 0),
            time=str(raw.get("time", "")),
            weekdays=sorted({int(d) for d in raw.get("weekdays", []) or []}),
            expr=str(raw.get("expr", "")),
            event=str(raw.get("event", "")),
            params=dict(raw.get("params", {}) or {}),
            tz=str(raw.get("tz", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Job:
    name: str
    trigger: Trigger
    prompt: str
    id: str = field(default_factory=new_id)
    enabled: bool = True
    session: str = DEFAULT_SESSION
    allowed_tools: list[str] = field(default_factory=list)  # 在默认无人值守白名单之外额外放行的
    misfire: str = MISFIRE_RUN_ONCE
    on_interrupt: str = "notify"
    timeout_s: int = DEFAULT_TIMEOUT_S
    active_hours: str = ""            # "08:00-23:00"；跨夜写 "22:00-06:00"；空 = 不限
    idle_only: bool = True            # 前台有任务时等待（OpenClaw idleOnly）
    scratch: str | None = None        # 私有检查清单；None=没有清单照常跑，""=清单为空
    skip_if_scratch_empty: bool = True
    next_fire_at: str = ""
    last_run_id: str = ""
    last_state: str = ""
    consecutive_failures: int = 0
    disabled_reason: str = ""
    state: dict[str, Any] = field(default_factory=dict)      # 事件触发的去重记录等
    created_by: str = "user"
    created_at: str = field(default_factory=lambda: to_iso(now_utc()))
    updated_at: str = field(default_factory=lambda: to_iso(now_utc()))

    def validate(self) -> None:
        if not self.name.strip():
            raise SchedulerError("任务名称不能为空")
        if not self.prompt.strip():
            raise SchedulerError("任务内容（要让智能体做什么）不能为空")
        if self.misfire not in MISFIRE_POLICIES:
            raise SchedulerError(f"未知的错过策略：{self.misfire}")
        if self.on_interrupt not in ON_INTERRUPT:
            raise SchedulerError(f"未知的中断策略：{self.on_interrupt}")
        if not 30 <= int(self.timeout_s) <= 6 * 3600:
            raise SchedulerError("单次超时应在 30 秒到 6 小时之间")
        if self.active_hours and not _WINDOW_RE.match(self.active_hours):
            raise SchedulerError("执行时间窗格式应为 HH:MM-HH:MM，例如 08:00-23:00")
        self.trigger.validate()

    def touch(self) -> None:
        self.updated_at = to_iso(now_utc())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Job:
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known and k != "trigger"}
        return cls(trigger=Trigger.from_dict(raw.get("trigger", {}) or {}), **data)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["trigger"] = self.trigger.to_dict()
        return out


@dataclass
class RunRecord:
    job_id: str
    reason: str                       # "schedule" / "misfire" / "manual" / "event:goal_stale" / "retry_interrupted"
    state: str = RUN_RUNNING
    run_id: str = field(default_factory=lambda: "sch-" + new_id())
    job_name: str = ""
    started_at: str = field(default_factory=lambda: to_iso(now_utc()))
    finished_at: str = ""
    summary: str = ""
    quiet: bool = False               # 智能体回复 NO_REPLY：成功但不打扰
    denied_tools: list[str] = field(default_factory=list)
    evidence_id: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RunRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    """runner 回调的返回值（引擎不关心执行细节，只要结果）。"""

    ok: bool
    summary: str = ""
    denied_tools: list[str] = field(default_factory=list)
    evidence_id: str = ""
