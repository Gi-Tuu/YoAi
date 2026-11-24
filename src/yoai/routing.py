"""YoAi 侧路由扩展：Core 规则表漏掉的高置信意图导向 REACT（2026-11-24）。

背景：
Core 的 AdaptiveRouter 用关键词表 _ACTION_HINTS 判行动意图，但覆盖有盲区——
- 有"记录"无"记住" → "记住我偏好X"被判 DIRECT，模型吐 DSML 被拒
- 有"读取"无"读一下/写个文件" → 文件操作被判 DIRECT（开了 builtin_tools 后同样失败）
DIRECT 不注入工具 schema，模型只能照 system prompt 的工具目录文本吐出 DSML，
Core 安全防线拒绝执行 → 任务没做 + 静默错误。

不改内核（内核要能跟随 Core 更新）——用 Core 已提供的 RouteSelector SPI
（AgentCore 的 learning= 参数）在 YoAi 侧补上这些意图。
Core 的规则/LLM 路径对其它任务完全不变。

用法：YoAiAgent 构造时默认注入；传 memory_intent_routing=False 关闭。
"""
from __future__ import annotations

import re
from typing import Any

from yai_core.types import Strategy

# 记忆写入意图：明确要求"把某事存下来"，必须走工具循环。
_MEMORY_WRITE = re.compile(
    r"(记住|记一下|记下来|请记|帮我记|别忘了|"
    r"我叫|我喜欢|我爱|我讨厌|我偏好|我在|我住在|我来自|我有|"
    r"我的(名字|生日|爱好|工作|家|家人|猫|狗|车|偏好))",
    re.IGNORECASE,
)

# 记忆查询意图：这些句子里的"记住"是描述不是写入，交回 Core 规则
# （Core 的"列出/查"已能命中 REACT）。
_MEMORY_QUERY = re.compile(r"(列出|查询|看看|有哪些|告诉我之前|我上次说过)")

# 文件操作意图：只在 registry 有 file_* 工具时才有意义（suggest 里检查）。
# "写/建/保存/读一下/打开看看"等 Core 规则表未覆盖的高置信文件动词。
_FILE_OP = re.compile(
    r"(写一个|写个|写入|保存到|新建文件|创建文件|建一个文件|"
    r"读一下|读读|打开.*文件|文件.*内容|把.*写入|"
    r"file_(read|create|patch|list))",
    re.IGNORECASE,
)


class MemoryIntentSelector:
    """把 Core 规则漏掉的高置信工具意图导向 REACT，其余不表态（返回 None）。

    类名保留 MemoryIntentSelector 以兼容既有引用；职责已扩展到文件操作。
    实现 Core 的 RouteSelector Protocol：
    - suggest(): 纯本地正则匹配，零网络/零模型调用，可放路由热路径
    - record(): 空实现——这是确定性规则，不是学习器，不消费反馈
    """

    source = "yoai:builtin-intent"

    def suggest(self, task: str, registry: Any) -> Any | None:
        text = str(task or "").strip()
        names = set()
        try:
            names = {s.name for s in registry.all()}
        except Exception:  # noqa: BLE001 - registry 鸭子类型容错
            pass
        # 空任务/无工具是 Core 的硬规则区，不越过
        if not text or not names:
            return None

        memory_hit = bool(_MEMORY_WRITE.search(text)) and not _MEMORY_QUERY.search(text)
        # 文件意图只有装了 file_* 工具时才接管（没工具时交回 Core，避免空转）
        has_file_tools = any(n.startswith("file_") for n in names)
        file_hit = has_file_tools and bool(_FILE_OP.search(text))
        if not (memory_hit or file_hit):
            return None

        from yai_core.learning.bandit import RouteSuggestion
        return RouteSuggestion(
            strategy=Strategy.REACT,
            source=self.source,
            confidence=0.95,   # 确定性规则，非统计学习
        )

    def record(self, task: str, registry: Any, chosen: Strategy, outcome: Any) -> None:
        return  # 规则选择器不需要反馈
