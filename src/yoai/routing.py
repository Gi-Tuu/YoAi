"""YoAi 侧路由：有工具就给 schema，让模型自己决定调不调（2026-11-24 根治版）。

## 为什么要换掉词表补丁

之前的方案是在 Core 的 `_ACTION_HINTS` 盲区上打地鼠：漏了"记住"补"记住"，
漏了"写文件"补"写文件"——词表永远补不全，下一个动词照样静默失败。

根因不是词表不全，是 **DIRECT 模式的设计矛盾**：
- DIRECT 不注入工具 JSON Schema（use_tools=False）
- 但 system prompt 仍注入工具能力目录（文本）
- 模型看到目录、没 schema → 把调用写成正文 DSML → Core 安全防线拒绝 → 静默失败

DIRECT 的收益只是省 4.2KB schema（18 工具实测）+ 一轮工具循环——
而模型不调工具时 REACT 也就一轮，收益几乎为零，代价却是整个静默失败问题类。

## 方案

继承 Core 的 AdaptiveRouter（公开类，不改内核），覆盖决策方法：
- 无工具 → 交回父类（CLARIFY / DIRECT 硬规则，能力边界优先）
- 有工具 → 一律 REACT（含完整 schema），让模型自己决定调不调
- 保留 CLARIFY（模糊任务仍先反问，不硬调工具）

Core 升级天然兼容：只用公开 API + 继承扩展，没有改内核文件、没有 monkey patch。

用法：YoAiAgent 构造时默认注入；传 memory_intent_routing=False 可关闭
（参数名保留兼容，语义已泛化为"YoAi 自主路由"）。
"""
from __future__ import annotations

from typing import Any

from yai_core.kernel.router import AdaptiveRouter, RouteDecision
from yai_core.types import Strategy


class YoAiRouter(AdaptiveRouter):
    """有工具时始终走 REACT，消除 DIRECT 的无 schema 矛盾。

    继承 AdaptiveRouter 保留全部构造参数与 LLM/学习器能力；
    只覆盖"有工具但规则想走 DIRECT"这一种决策。
    """

    def _should_use_react(self, task: str, registry: Any) -> bool:
        text = str(task or "").strip()
        try:
            n = len(registry)
        except Exception:  # noqa: BLE001
            n = 0
        if not text or n == 0:
            return False   # 硬规则区交回父类
        # 父类判 CLARIFY 的模糊短句仍交回父类（先反问，不硬调工具）
        try:
            parent = super()._rules(text, registry)
        except Exception:  # noqa: BLE001
            return True
        if parent.strategy == Strategy.CLARIFY:
            return False
        return True

    def classify(self, task: str, registry: Any) -> Strategy:
        if self._should_use_react(task, registry):
            return Strategy.REACT
        return super().classify(task, registry)

    async def aclassify(
        self,
        task: str,
        registry: Any,
        *,
        discoverable: list[dict[str, str]] | None = None,
    ) -> RouteDecision:
        if self._should_use_react(task, registry):
            return RouteDecision(
                strategy=Strategy.REACT,
                source="yoai:tools-first",
                reason="宿主有工具，注入完整 schema 由模型自行决定（消除 DIRECT 无 schema 矛盾）",
                tier="standard",
            )
        return await super().aclassify(task, registry, discoverable=discoverable)


# 兼容旧引用：此前叫 MemoryIntentSelector，现在语义是"工具优先路由"。
# 保留别名避免外部 import 断裂。
MemoryIntentSelector = YoAiRouter
