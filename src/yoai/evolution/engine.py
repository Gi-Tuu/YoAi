"""进化引擎 · M2：编排归因 → 门控 → 候选生成 → 隔离评测 → 晋升/保留。

设计单 §3 流程的完整落地：
  任务 → 选专家 → 执行 → 结果归因 → 产生候选分支 → 独立评测 → 晋升或保留原版

诚实原则：
- 进化并非每次任务后必然发生（环境问题/成功不产生分支）。
- 新节点从本次实际执行节点继承，不覆盖父节点。
- 隔离评测样本不足 / 退化 → 保留原版，不晋升。
- 全流程产出可审计 EvolutionReport（为什么进化/为什么不进化/评测结论/晋升决策）。

不自动在每次对话后触发（避免无意义分支泛滥）；由宿主显式调用或低影响任务试用触发。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from yoai.evidence.attribution import AttributionEngine
from yoai.evidence.models import Attribution, ExecutionEvidence
from yoai.evidence.store import EvidenceStore
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.candidate import CandidateGenerator, CandidateProposal
from yoai.evolution.promotion import PromotionDecision, PromotionGate


@dataclass
class EvolutionReport:
    """一次进化尝试的完整审计记录。"""

    id: str
    evidence_id: str
    triggered: bool                    # 是否真的产生了候选
    cause: str                         # 归因类别
    attribution: Attribution | None
    proposal: CandidateProposal | None
    new_node_id: str | None
    promotion: PromotionDecision | None
    reason: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "evidence_id": self.evidence_id,
            "triggered": self.triggered, "cause": self.cause,
            "attribution": self.attribution.to_dict() if self.attribution else None,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "new_node_id": self.new_node_id,
            "promotion": self.promotion.to_dict() if self.promotion else None,
            "reason": self.reason, "created_at": self.created_at,
        }


class EvolutionEngine:
    """进化引擎：一次任务证据 → 是否进化 → 候选 → 评测 → 晋升决策。"""

    def __init__(
        self,
        archive: EvolutionArchive,
        store: EvidenceStore,
        *,
        min_trial_samples: int = 3,
    ) -> None:
        self.archive = archive
        self.store = store
        self.attributor = AttributionEngine(store)
        self.generator = CandidateGenerator(archive)
        self.gate = PromotionGate(archive, store, min_trial_samples=min_trial_samples)
        self._reports: dict[str, EvolutionReport] = {}

    def evolve(self, evidence_id: str) -> EvolutionReport:
        """对一条执行证据尝试进化；不触发时返回 triggered=False。"""
        evidence = self.store.get(evidence_id)
        if evidence is None:
            return self._report(evidence_id, False, "missing", None, None, None, None,
                                "证据不存在，不进化")

        attribution = self.store.attribution_for(evidence_id) or self.attributor.attribute(evidence)
        if self.store.attribution_for(evidence_id) is None:
            self.store.add_attribution(attribution)

        proposal = self.generator.propose(evidence, attribution)
        if proposal is None:
            return self._report(
                evidence_id, False, attribution.cause, attribution, None, None, None,
                f"归因 {attribution.cause} 不触发进化（环境问题/成功不产生无意义分支）",
            )

        # 从实际执行节点派生候选（candidate 状态，不覆盖父节点）
        node = self.archive.create_child(
            proposal.parent_id, proposal.name, proposal.spec, diff=proposal.diff,
        )
        # 把这次执行证据挂到新节点，供后续评测/试用消费
        from yoai.evolution.models import EvidenceRef
        self.archive.add_evidence(
            node.id,
            EvidenceRef(
                id=evidence.id, kind="evolution_source",
                task_fingerprint=evidence.task_fingerprint,
                outcome="partial", detail=proposal.reason,
            ),
        )

        # 用隔离验证样本评测候选 → 晋升 probation 或保留
        decision = self.gate.evaluate_probation(node.id, proposal.parent_id)
        self.archive.add_evidence(
            node.id,
            EvidenceRef(
                id=uuid.uuid4().hex[:10], kind="promotion",
                task_fingerprint=evidence.task_fingerprint,
                outcome="pass" if decision.promoted else "fail",
                detail=decision.reason,
            ),
        )
        report = self._report(
            evidence_id, True, attribution.cause, attribution, proposal,
            node.id, decision,
            f"候选 {node.id} 已创建；晋升决策：{decision.reason}",
        )
        return report

    def try_promote_active(self, node_id: str) -> PromotionDecision:
        """probation 节点试用证据达标 → active。供宿主在真实任务后调用。"""
        return self.gate.evaluate_active(node_id)

    def check_regression(self, node_id: str) -> PromotionDecision:
        """active 节点隔离评测退化 → retired。"""
        parent = self.archive.get(node_id)
        parent_id = parent.parent_id if parent else None
        return self.gate.retire_if_regressed(node_id, parent_id)

    def reports(self) -> list[EvolutionReport]:
        return list(self._reports.values())

    def get_report(self, report_id: str) -> EvolutionReport | None:
        return self._reports.get(report_id)

    def _report(
        self, evidence_id, triggered, cause, attribution, proposal, new_node_id, promotion, reason
    ) -> EvolutionReport:
        r = EvolutionReport(
            id=uuid.uuid4().hex[:10], evidence_id=evidence_id,
            triggered=triggered, cause=cause, attribution=attribution,
            proposal=proposal, new_node_id=new_node_id,
            promotion=promotion, reason=reason,
        )
        self._reports[r.id] = r
        # 进化报告也落证据库（可审计、跨会话可读）
        self.store.add_evolution_report(r.to_dict())
        return r
