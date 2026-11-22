"""候选生成器 · M2：基于归因与证据从实际执行节点派生候选分支。

诚实原则（设计单 §3/§4）：
- 不是每次任务都进化：只在 capability / routing 归因时生成候选。
- environment（工具/网关问题）→ 不生成分支（改专家解决不了环境问题）。
- none/成功 → 不生成分支。
- 新节点从**本次实际执行节点**派生，不覆盖父节点、不默认从最新节点继承。
- 改动是确定性规则（可解释、可审计），不靠模型凭空发挥；diff 记录为什么改。

原型边界：候选的"能力增强"是很朴素的规则扩展（补工具白名单、补能力标签、补提示），
真正的"策略改写"留给未来；这里先让进化链闭环、可验证、不造假。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoai.evidence.models import (
    ATTRIBUTION_CAPABILITY,
    ATTRIBUTION_ENVIRONMENT,
    ATTRIBUTION_NONE,
    ATTRIBUTION_ROUTING,
    Attribution,
    ExecutionEvidence,
)
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.models import ExpertNode, ExpertSpec


@dataclass
class CandidateProposal:
    """一个候选提案（还没写进档案）。"""

    parent_id: str
    name: str
    spec: ExpertSpec
    diff: dict[str, Any]
    cause: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_id": self.parent_id, "name": self.name,
            "spec": self.spec.to_dict(), "diff": dict(self.diff),
            "cause": self.cause, "reason": self.reason,
        }


class CandidateGenerator:
    """基于归因 + 证据生成候选提案，不直接改档案。"""

    def __init__(self, archive: EvolutionArchive) -> None:
        self.archive = archive

    def propose(
        self,
        evidence: ExecutionEvidence,
        attribution: Attribution,
    ) -> CandidateProposal | None:
        """返回候选提案；不该进化时返回 None（明确不制造分支）。"""
        if attribution.cause in (ATTRIBUTION_NONE, ATTRIBUTION_ENVIRONMENT):
            return None

        parent_id = evidence.expert_id
        parent = self.archive.get(parent_id) if parent_id else self.archive.root
        if parent is None:
            return None

        if attribution.cause == ATTRIBUTION_CAPABILITY:
            return self._capability_candidate(parent, evidence, attribution)
        if attribution.cause == ATTRIBUTION_ROUTING:
            return self._routing_candidate(parent, evidence, attribution)
        return None

    def _capability_candidate(
        self, parent: ExpertNode, e: ExecutionEvidence, a: Attribution
    ) -> CandidateProposal:
        """能力不足：补本次用过的工具 + 加'先核对状态'的提示。"""
        tools = set(parent.spec.tools) | set(e.tool_calls)
        hint = "执行后先核对实际状态，不要仅凭工具回执声称完成。"
        suffix_parts = [s for s in (parent.spec.prompt_suffix, hint) if s]
        new_spec = ExpertSpec(
            tools=tuple(sorted(tools)),
            strategy_bias=parent.spec.strategy_bias,
            prompt_suffix="\n".join(suffix_parts),
            model_tier=parent.spec.model_tier,
            budget=dict(parent.spec.budget) if parent.spec.budget else None,
            capability_tags=parent.spec.capability_tags,
        )
        return CandidateProposal(
            parent_id=parent.id,
            name=f"{parent.name}·能力增强",
            spec=new_spec,
            diff={
                "cause": a.cause,
                "tools_added": sorted(set(e.tool_calls) - set(parent.spec.tools)),
                "prompt_added": hint,
                "reason": a.reason,
            },
            cause=a.cause,
            reason=f"能力不足（{a.reason}）：补工具白名单 + 状态核对提示",
        )

    def _routing_candidate(
        self, parent: ExpertNode, e: ExecutionEvidence, a: Attribution
    ) -> CandidateProposal:
        """路由不适配：把本任务指纹标签补进能力标签，让下次能选中它。"""
        tags = set(parent.spec.capability_tags) | set(e.fingerprint_tags)
        new_spec = ExpertSpec(
            tools=parent.spec.tools,
            strategy_bias=parent.spec.strategy_bias,
            prompt_suffix=parent.spec.prompt_suffix,
            model_tier=parent.spec.model_tier,
            budget=dict(parent.spec.budget) if parent.spec.budget else None,
            capability_tags=tuple(sorted(tags)),
        )
        return CandidateProposal(
            parent_id=parent.id,
            name=f"{parent.name}·路由适配",
            spec=new_spec,
            diff={
                "cause": a.cause,
                "tags_added": sorted(set(e.fingerprint_tags) - set(parent.spec.capability_tags)),
                "reason": a.reason,
            },
            cause=a.cause,
            reason=f"路由不适配（{a.reason}）：补能力标签让下次能选中本专家",
        )
