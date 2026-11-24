"""YoAi 侧路由扩展：记忆写入意图必须拿到工具 schema（走 REACT）。

背景（2026-11-24 真实生产诊断）：
Core 的 AdaptiveRouter 用关键词表 _ACTION_HINTS 判行动意图，里面有"记录"但没有
"记住"——用户说"记住我偏好深色主题"被判成 DIRECT（无需工具）。DIRECT 不注入
工具 schema，模型只能照 system prompt 的工具目录文本吐出 DSML，Core 严格拒绝，
结果：没记住 + 一条用户看不到的 error。

这是 Core 规则的覆盖盲区，不改内核（内核要能跟随上游更新）——用 Core 已提供的
RouteSelector SPI（AgentCore 的 learning= 参数）在 YoAi 侧补上这类意图。
Core 的规则/LLM 路径对其它任务完全不变。

用法：YoAiAgent 构造时默认注入；也可传 route_selector=False 关闭以兼容旧行为。
"""
from __future__ import annotations

import re
from typing import Any

from yai_core.types import Strategy

# 记忆写入意图：这些句式明确要求"把某事存下来"，必须走工具循环。
# 只列高置信度模式——宁可漏（回退 Core 规则）不可滥（把闲聊也塞进 REACT）。
_WRITE_INTENT = re.compile(
    r"(记住|记一下|记下来|请记|帮我记|别忘了|别忘了告诉我|"
    r"我叫|我叫什么|我喜欢|我爱|我讨厌|我偏好|我在|我住在|我来自|我有|"
    r"我的(名字|生日|爱好|工作|家|家人|猫|狗|车|偏好))",
    re.IGNORECASE,
)

# 查询意图优先排除："列出我记住的事"含"记住"但是查询，Core 规则已能识别"列出"。
# 这类交给 Core 规则，避免扩展越过职责边界。
_QUERY_INTENT = re.compile(r"(列出|查询|查看|看看|有哪些|是什么|告诉我|读一下|读取)")


class MemoryIntentSelector:
    """把明确的记忆写入意图导向 REACT，其余任务不表态（返回 None）。

    实现 Core 的 RouteSelector Protocol：
    - suggest(): 纯本地正则匹配，零网络/零模型调用，可放路由热路径
    - record(): 空实现——这是确定性规则，不是学习器，不消费反馈
    """

    source = "yoai:memory-intent"

    def suggest(self, task: str, registry: Any) -> Any | None:
        text = str(task or "").strip()
        # 空任务/无工具是 Core 的硬规则区，不越过
        if not text or not getattr(registry, "__len__", lambda: 0)():
            return None
        if _QUERY_INTENT.search(text):
            return None   # 查询类交回 Core 规则（"列出"已能命中 REACT）
        if not _WRITE_INTENT.search(text):
            return None
        # 延迟导入，避免模块导入期依赖 Core 的可选 learning 包
        from yai_core.learning.bandit import RouteSuggestion
        return RouteSuggestion(
            strategy=Strategy.REACT,
            source=self.source,
            confidence=0.95,   # 确定性规则，非统计学习
        )

    def record(self, task: str, registry: Any, chosen: Strategy, outcome: Any) -> None:
        return  # 规则选择器不需要反馈
