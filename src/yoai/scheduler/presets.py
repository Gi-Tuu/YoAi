"""预置任务（对齐 OpenClaw：首次启动预置一个「主动检查」任务，默认关闭）。

OpenClaw 的 heartbeat 已迁移为普通的定时任务：默认每 30 分钟、等前台空闲、
清单为空就跳过、没有需要报告的就回复 NO_REPLY。YoAi 照此预置，但**默认不开**——
用户在「定时」页或对话里打开后才运行。只预置一次：用户删掉后不会再自动出现。
"""

from __future__ import annotations

from yoai.scheduler.models import MISFIRE_SKIP, Job, Trigger

HEARTBEAT_ID = "heartbeat"

HEARTBEAT_PROMPT = (
    "这是一次定时主动检查。先阅读下面的检查清单，需要时用 list_goals、recent_events "
    "等工具查看现状。只报告需要我注意、而且我可以采取行动的变化，每条一句话；"
    "如果没有，就只回复 NO_REPLY。"
)

DEFAULT_CHECKLIST = (
    "- 进行中的目标里，有没有超过 3 天没有进展的？\n"
    "- 最近记下的事情里，有没有今天或明天到期的？"
)


def heartbeat_job() -> Job:
    return Job(
        id=HEARTBEAT_ID,
        name="主动检查",
        trigger=Trigger(kind="interval", every_s=1800),
        prompt=HEARTBEAT_PROMPT,
        enabled=False,
        active_hours="08:00-23:00",
        idle_only=True,
        scratch=DEFAULT_CHECKLIST,
        misfire=MISFIRE_SKIP,          # 心跳没有补跑的意义
        created_by="preset",
    )


def morning_review_job(time_: str = "09:00") -> Job:
    return Job(
        name="早间目标回顾",
        trigger=Trigger(kind="daily", time=time_),
        prompt="列出我进行中的目标，每个目标给一句今天可以推进的具体建议。",
        created_by="preset",
    )
