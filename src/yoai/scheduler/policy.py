"""无人值守权限（方案第 6 节）：定时任务没有人能点审批弹窗，所以 fail closed。

拍板（2026-11-27）：默认 = 只读 + 记忆/目标内部写。
白名单外的工具**直接拒绝、不弹窗**，并记录到运行结果里。

本模块不依赖 Core；S2 接入 runtime 时，用 ``UnattendedGate`` 作为审批回调
（替代会弹窗的 ``_request_host``），并按 ``allowed_set`` 构造 AllowlistPolicy。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 只读：查记忆 / 查文件 / 联网读
READ_ONLY_TOOLS = frozenset({
    "all_topics", "events_between", "facts_by_tag", "list_facts", "list_goals",
    "recall_fact", "related_events", "summarize_theme",
    "file_list", "file_read", "file_ro_list", "file_ro_read",
    "proj_list", "proj_read",
    "web_search", "web_fetch",
    "now", "recent_events", "list_tools",
    "schedule_list",
})

# 记忆 / 目标内部写（只改 YoAi 自己的状态，不碰用户文件和系统）
MEMORY_WRITE_TOOLS = frozenset({
    "remember_event", "remember_fact", "create_goal", "complete_goal",
})

# 永远不允许无人值守——即使用户在 allowed_tools 里勾了也不放行
NEVER_UNATTENDED = frozenset({
    "shell_run",                   # 执行命令
    "forget_fact", "forget_event", # 删除记忆
    "proj_write", "proj_patch",    # 改项目文件
    "file_create", "file_patch",   # 写工作区文件
    "open_url",                    # 无人时弹系统浏览器没有意义，也可被注入利用
    "schedule_create", "schedule_cancel", "schedule_run_now",  # 定时任务不能自我繁殖
    "skill_run", "ct_anchor",      # 执行技能脚本 / 向外提交
})

DEFAULT_UNATTENDED = READ_ONLY_TOOLS | MEMORY_WRITE_TOOLS


def is_never_allowed(tool: str) -> bool:
    """黑名单 + 所有外部扩展工具（MCP/Skill 以前缀区分）默认不放行。"""
    if tool in NEVER_UNATTENDED:
        return True
    return tool.startswith(("mcp__", "mcp.", "skill__", "skill."))


def allowed_set(extra: list[str] | tuple[str, ...] = ()) -> set[str]:
    """默认白名单 ∪ 用户额外勾选，再剔除永不放行的。"""
    return {t for t in (DEFAULT_UNATTENDED | set(extra)) if not is_never_allowed(t)}


@dataclass
class UnattendedGate:
    """审批回调替身：不弹窗，按白名单立即给出 allow/deny，并记账。"""

    extra: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._allowed = allowed_set(self.extra)

    def decide(self, tool: str) -> bool:
        if tool in self._allowed:
            return True
        if tool not in self.denied:
            self.denied.append(tool)
        return False
