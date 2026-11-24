"""YoAi Capabilities — 暴露给 Core 内省的宿主业务能力。

这些是普通业务方法，没有任何 Agent 代码。AgentCore 通过内省把它们
变成工具（见 Core 的 discovery/introspect.py）。YoAi 与 Core 的职责边界：
Core 决定"何时调用、如何规划、如何执行"，这里只提供"个人上下文与目标"能力。
"""

from __future__ import annotations

from typing import Any

from yoai.context import PersonalContext
from yoai.goals import GoalManager
from yoai.temporal_memory import TemporalMemory


class PersonalCapabilities:
    """把 Personal Context + Goal Manager 包装成一组可内省的工具方法。

    temporal_memory 可选：注入后额外暴露"带发生时间"的事件记忆工具，
    用于时间推理与跨会话聚合。不注入则工具集与旧版完全一致（向后兼容）。
    """

    def __init__(
        self,
        context: PersonalContext,
        goals: GoalManager,
        temporal_memory: TemporalMemory | None = None,
    ) -> None:
        self._context = context
        self._goals = goals
        self._tmem = temporal_memory

    # --- Personal Context 工具 ---
    def remember_fact(self, key: str, value: str, tag: str = "") -> str:
        """记住一条关于用户的个人事实或偏好，例如暗色主题、常用项目。"""
        return self._context.remember(key, value, tag=tag)

    def recall_fact(self, key: str) -> str:
        """按名称取回一条已记住的个人事实。"""
        value = self._context.recall(key)
        return "未找到" if value is None else str(value)

    def list_facts(self) -> dict[str, Any]:
        """列出全部已记住的个人事实。"""
        return self._context.list_all()

    def forget_fact(self, key: str) -> str:
        """删除一条已记住的个人事实（按键名精确匹配）。删除不可恢复；
        键名不确定时先用 list_facts 查准确键名。"""
        removed = self._context.forget(key)
        return f"已删除：{key}" if removed else f"没有名为 {key} 的事实（先用 list_facts 查）"

    def now(self) -> str:
        """当前本地时间（ISO 8601 带时区）。给事件打 event_time、排序、
        算"多久之前"都需要先取这个真实时钟，不要自己猜时间。"""
        from datetime import datetime
        return datetime.now().astimezone().isoformat(timespec="seconds")

    # --- Goal Manager 工具 ---
    def create_goal(self, title: str, steps: list[str] | None = None) -> str:
        """创建一个长期目标，可附带步骤列表，返回目标 id。"""
        return self._goals.create_goal(title, steps)

    def complete_goal(self, goal_id: str) -> bool:
        """把一个长期目标标记为已完成。"""
        return self._goals.set_status(goal_id, "done")

    def list_goals(self) -> list[dict[str, Any]]:
        """列出全部长期目标及其状态。"""
        return self._goals.list_goals()

    # --- 时间记忆工具（可选，注入 temporal_memory 后可用）---
    def remember_event(
        self, what: str, event_time: str = "", tag: str = "",
        topics: list[str] | None = None, speaker: str = "user",
    ) -> str:
        """记住一件带发生时间的事。event_time 用 ISO 8601；topics 填细粒度主题便于跨会话聚合；
        speaker 填 user 或 assistant（助手给出的资源/结论也要记）。"""
        if self._tmem is None:
            return "时间记忆未启用"
        return self._tmem.remember_event(
            what, event_time=event_time, tag=tag, topics=topics, speaker=speaker
        )

    def events_between(self, start: str, end: str) -> list[dict[str, Any]]:
        """查某段时间（ISO 8601）内发生了哪些事，按时间排序。"""
        if self._tmem is None:
            return []
        return self._tmem.events_between(start, end)

    def facts_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """按主题聚合所有相关事件，用于跨会话汇总（如统计手足总数）。"""
        if self._tmem is None:
            return []
        return self._tmem.facts_by_tag(tag)

    def related_events(self, topic: str) -> list[dict[str, Any]]:
        """按细粒度主题（如 jewelry / camping）找出所有相关事件，跨会话取全。"""
        if self._tmem is None:
            return []
        return self._tmem.related_events(topic)

    def summarize_theme(self, topic: str) -> dict[str, Any]:
        """汇总某主题的全部事件与数量，用于"总共几件/多少次"类求和题。"""
        if self._tmem is None:
            return {"topic": topic, "count": 0, "events": []}
        return self._tmem.summarize_theme(topic)

    def all_topics(self) -> list[str]:
        """列出所有已知主题，帮助发现该查什么。"""
        return [] if self._tmem is None else self._tmem.all_topics()

    def recent_events(self, n: int = 10) -> list[dict[str, Any]]:
        """最近 n 条事件（新的在前）。删除前先用它核对事件的准确原文。"""
        if self._tmem is None:
            return []
        return self._tmem.recent_events(n)

    def forget_event(self, what: str, tag: str = "") -> str:
        """删除一条已记住的事件（按 what 原文精确匹配，tag 可选收窄）。
        删除不可恢复；what 必须用 recent_events / facts_by_tag 查到的准确原文，
        不要凭记忆改写。"""
        if self._tmem is None:
            return "时间记忆未启用"
        count = self._tmem.forget(what, tag=tag)
        if count == 0:
            return "没有精确匹配的事件（先用 recent_events / facts_by_tag 查准确原文）"
        return f"已删除 {count} 条匹配事件"
