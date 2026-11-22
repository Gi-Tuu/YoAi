"""ExpertModelProvider — 把 M1 路由决策真实接入主对话模型调用。

作用（回答"expert_id 接进证据"的正确做法）：
- 每次 achat 前，从 messages 提取当前任务文本，调用 ExpertRouter 做一次真实路由决策；
- 把选中 active 专家的 prompt_suffix 注入 system 消息 —— 专家真的参与了执行，
  而不是只在证据里填个假 id；
- 把 RouteDecision 暴露给证据采集器（last_decision / last_expert_id / last_parent_id），
  让归因能定位到"本次是哪个专家在干活"。

两层路由边界保持不变：
- 本 provider 决定"谁执行"（专家节点，产出 prompt_suffix 影响能力切面）；
- Core 的 AdaptiveRouter 仍决定"怎么执行"（direct/react/plan/clarify），不被这里篡改。
- 路由决策的 strategy_bias 仅作为**提示**注入 system，不改写 Core 的路由参数。
"""

from __future__ import annotations

from typing import Any

from yai_core.types import ModelResponse

from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.router import ExpertRouter, RouteDecision


class ExpertModelProvider:
    """包装任意 ModelProvider，在每次调用前按任务选专家并注入能力提示。"""

    yai_multimodal = False   # 包装层不声明多模态（除非 base 支持，见下）

    def __init__(
        self,
        base_provider: Any,
        router: ExpertRouter,
        archive: EvolutionArchive,
    ) -> None:
        self.base = base_provider
        self.router = router
        self.archive = archive
        self.yai_multimodal = bool(getattr(base_provider, "yai_multimodal", False))
        self.last_decision: RouteDecision | None = None
        self.calls = 0

    @property
    def total_usage(self) -> dict[str, int]:
        """转发 base provider 的真实累计用量（证据采集读这里）。"""
        return getattr(self.base, "total_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    @property
    def last_expert_id(self) -> str | None:
        return self.last_decision.selected_id if self.last_decision else None

    @property
    def last_parent_id(self) -> str | None:
        """选中专家的父节点 id（评测对照用）。"""
        if not self.last_decision or not self.last_decision.selected_id:
            return None
        node = self.archive.get(self.last_decision.selected_id)
        return node.parent_id if node else None

    def tools_for(self, task: str) -> set[str] | None:
        """本次任务允许的工具白名单（专家能力接线的关键）。

        - 先做一次真实路由（与 achat 里同任务、确定性，结果一致）；
        - 返回选中专家的 spec.tools；空集表示"不限制"→ 返回 None（向后兼容，
          root 节点 tools=() 即全部工具）；
        - 供 YoAiAgent 在 astream 开始时过滤工具注册表。
        """
        decision = self.router.route(task) if task else None
        self.last_decision = decision
        if not decision or not decision.selected_id:
            return None
        node = self.archive.get(decision.selected_id)
        if not node or not node.spec.tools:
            return None
        return set(node.spec.tools)

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        self.calls += 1
        task = self._extract_task(messages)
        decision = self.router.route(task) if task else None
        self.last_decision = decision

        enhanced = self._inject_expert(messages, decision)
        return await self.base.achat(enhanced, tools, tier=tier)

    @staticmethod
    def _extract_task(messages: list[dict[str, Any]]) -> str:
        """最后一条 user 文本即当前任务。"""
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        str(p.get("text", "")) for p in content
                        if isinstance(p, dict)
                    )
                return str(content) if isinstance(content, str) else ""
        return ""

    def _inject_expert(
        self, messages: list[dict[str, Any]], decision: RouteDecision | None
    ) -> list[dict[str, Any]]:
        """把选中专家的 prompt_suffix 注入 system（真实能力切面）。"""
        if not decision or not decision.selected_id:
            return messages
        node = self.archive.get(decision.selected_id)
        if not node or not node.spec.prompt_suffix:
            return messages

        hint = f"[专家节点：{node.name}] {node.spec.prompt_suffix}"
        out = list(messages)
        for i, m in enumerate(out):
            if m.get("role") == "system":
                content = m.get("content", "")
                if isinstance(content, str):
                    out[i] = {**m, "content": f"{content}\n{hint}"}
                break
        else:
            out.insert(0, {"role": "system", "content": hint})
        return out

    def describe(self) -> dict[str, Any]:
        return {
            "base": getattr(self.base, "name", type(self.base).__name__),
            "expert_id": self.last_expert_id,
            "parent_id": self.last_parent_id,
            "decision": self.last_decision.to_dict() if self.last_decision else None,
        }
