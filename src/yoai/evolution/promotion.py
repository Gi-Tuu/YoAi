"""晋升门 · M2：用隔离评测决定候选节点能否晋升。

生命周期（设计单 §5）：candidate → probation → active → retired。
- candidate → probation：离线隔离验证通过（BenchmarkLab 隔离评测 improved/no_regression，
  且样本足够）。样本不足 / regression → 留在 candidate，不晋升（诚实）。
- probation → active：有限试用通过（试用证据数量达标且无 verified_failure）。
- 退化但已 active → retired（退出默认路由，档案保留）。

所有判定可审计：返回 PromotionDecision 带理由、评测报告、样本量。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoai.evidence.benchmark_lab import BenchmarkLab, EvaluationReport
from yoai.evidence.models import ExecutionEvidence
from yoai.evidence.store import EvidenceStore
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.models import ExpertNode


@dataclass
class PromotionDecision:
    """一次晋升判定的完整审计记录。"""

    node_id: str
    from_state: str
    to_state: str           # 目标状态（可能等于 from_state = 不晋升）
    promoted: bool
    reason: str
    report: EvaluationReport | None
    trial_samples: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "from_state": self.from_state,
            "to_state": self.to_state, "promoted": self.promoted,
            "reason": self.reason,
            "report": self.report.to_dict() if self.report else None,
            "trial_samples": self.trial_samples,
        }


class PromotionGate:
    """基于隔离评测与试用证据的晋升门。"""

    def __init__(
        self,
        archive: EvolutionArchive,
        store: EvidenceStore,
        *,
        min_trial_samples: int = 3,
    ) -> None:
        self.archive = archive
        self.store = store
        self.lab = BenchmarkLab(store)
        self.min_trial_samples = min_trial_samples

    def evaluate_probation(
        self, node_id: str, parent_id: str | None = None
    ) -> PromotionDecision:
        """candidate → probation：用隔离验证样本评测。"""
        node = self.archive.get(node_id)
        if node is None:
            return PromotionDecision(node_id, "missing", "missing", False, "节点不存在", None, 0)
        if node.lifecycle != "candidate":
            return PromotionDecision(
                node_id, node.lifecycle, node.lifecycle, False,
                f"仅 candidate 可申请 probation（当前 {node.lifecycle}）", None, 0,
            )

        report = self.lab.evaluate(node_id, parent_id)
        if report.verdict in ("insufficient", "regression"):
            return PromotionDecision(
                node_id, "candidate", "candidate", False,
                f"不晋升：隔离评测结论 {report.verdict} —— {report.note}",
                report, report.total_samples,
            )
        # improved / no_regression → probation（有限试用）
        self.archive.transition(node_id, "probation")
        return PromotionDecision(
            node_id, "candidate", "probation", True,
            f"隔离评测 {report.verdict}：{report.note}", report, report.total_samples,
        )

    def evaluate_active(self, node_id: str) -> PromotionDecision:
        """probation → active：有限试用证据达标且无失败。"""
        node = self.archive.get(node_id)
        if node is None:
            return PromotionDecision(node_id, "missing", "missing", False, "节点不存在", None, 0)
        if node.lifecycle != "probation":
            return PromotionDecision(
                node_id, node.lifecycle, node.lifecycle, False,
                f"仅 probation 可申请 active（当前 {node.lifecycle}）", None, 0,
            )

        trials = [e for e in self.store.query(expert_id=node_id)
                  if e.sample_class == "validation"]
        failed = [
            e for e in trials
            if e.verification and e.verification.get("status") == "verified_failure"
        ]
        if len(trials) < self.min_trial_samples:
            return PromotionDecision(
                node_id, "probation", "probation", False,
                f"试用样本 {len(trials)} < {self.min_trial_samples}，继续试用",
                None, len(trials),
            )
        if failed:
            return PromotionDecision(
                node_id, "probation", "probation", False,
                f"试用中有 {len(failed)} 次验收失败，不晋升 active",
                None, len(trials),
            )
        self.archive.transition(node_id, "active")
        return PromotionDecision(
            node_id, "probation", "active", True,
            f"试用样本 {len(trials)} 全部通过，晋升 active", None, len(trials),
        )

    def retire_if_regressed(
        self, node_id: str, parent_id: str | None = None
    ) -> PromotionDecision:
        """active 节点隔离评测退化 → retired（保留档案）。"""
        node = self.archive.get(node_id)
        if node is None or node.lifecycle != "active":
            return PromotionDecision(
                node_id, node.lifecycle if node else "missing",
                node.lifecycle if node else "missing", False,
                "仅 active 可判定退化", None, 0,
            )
        report = self.lab.evaluate(node_id, parent_id)
        if report.verdict != "regression":
            return PromotionDecision(
                node_id, "active", "active", False,
                f"未发现退化（{report.verdict}）", report, report.total_samples,
            )
        self.archive.transition(node_id, "retired")
        return PromotionDecision(
            node_id, "active", "retired", True,
            f"隔离评测发现退化：{report.note}", report, report.total_samples,
        )
