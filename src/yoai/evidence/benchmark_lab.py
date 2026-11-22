"""样本隔离评测骨架 · BenchmarkLab。

设计单 §4：验证样本与进化样本隔离；对照父节点同条件评测；报告样本量与不确定性。

原型规则（保守、可解释）：
- 从 EvidenceStore 取"验证样本"（sample_class=validation），永不拿进化样本做晋升判断。
- 按任务指纹分组，对每个节点统计成功率；与父节点对照。
- 样本量 < min_samples 时不下结论（report.confident=False），写明"样本不足"。
- 不确定性用 Wilson 区间近似（小样本稳健），报告区间而非单点分数。
- 只评估"能力边界"：按 fingerprint_tags 分组报告，不只看综合分。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from yoai.evidence.models import ExecutionEvidence
from yoai.evidence.store import EvidenceStore


@dataclass
class BoundaryResult:
    """某个能力标签上的对照结果。"""

    capability_tag: str
    node_success: int
    node_total: int
    parent_success: int
    parent_total: int
    node_rate: float
    parent_rate: float
    node_ci: tuple[float, float]
    parent_ci: tuple[float, float]
    sample_enough: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_tag": self.capability_tag,
            "node_success": self.node_success, "node_total": self.node_total,
            "parent_success": self.parent_success, "parent_total": self.parent_total,
            "node_rate": round(self.node_rate, 3),
            "parent_rate": round(self.parent_rate, 3),
            "node_ci": [round(x, 3) for x in self.node_ci],
            "parent_ci": [round(x, 3) for x in self.parent_ci],
            "sample_enough": self.sample_enough,
        }


@dataclass
class EvaluationReport:
    """一份评测报告（可复现：带节点、样本类别、样本量、边界结果）。"""

    node_id: str
    parent_id: str | None
    sample_class: str
    total_samples: int
    boundaries: list[BoundaryResult]
    verdict: str            # improved / no_regression / insufficient / regression
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "parent_id": self.parent_id,
            "sample_class": self.sample_class,
            "total_samples": self.total_samples,
            "boundaries": [b.to_dict() for b in self.boundaries],
            "verdict": self.verdict, "note": self.note,
        }


class BenchmarkLab:
    """用隔离的验证样本评测候选节点（原型，不产模型判断）。"""

    def __init__(self, store: EvidenceStore, *, min_samples: int = 3, z: float = 1.96) -> None:
        self.store = store
        self.min_samples = min_samples
        self.z = z

    def evaluate(self, node_id: str, parent_id: str | None = None) -> EvaluationReport:
        """只用验证样本评测节点 vs 父节点。"""
        validation = self.store.validation_set()
        node_items = [e for e in validation if e.expert_id == node_id]
        parent_items = [e for e in validation if e.expert_id == parent_id] if parent_id else []

        tags = sorted({
            tag for e in node_items + parent_items for tag in e.fingerprint_tags
        })
        boundaries = [
            self._boundary(tag, node_items, parent_items) for tag in tags
        ] if tags else [self._boundary("(all)", node_items, parent_items)]

        total = len(node_items)
        if total < self.min_samples:
            verdict, note = "insufficient", f"验证样本仅 {total} 条（需 ≥{self.min_samples}），不下晋升结论"
        else:
            enough = [b for b in boundaries if b.sample_enough]
            if not enough:
                verdict, note = "insufficient", "各能力边界样本均不足，不下结论"
            elif any(b.node_ci[0] < b.parent_ci[0] - 0.05 for b in enough):
                verdict, note = "regression", "至少一个能力边界的置信下界低于父节点，存在退化风险"
            elif any(b.node_rate > b.parent_rate + 0.05 for b in enough):
                verdict, note = "improved", "至少一个能力边界在隔离验证样本上优于父节点"
            else:
                verdict, note = "no_regression", "隔离验证样本上未见显著退化，也未见明确提升"

        return EvaluationReport(
            node_id=node_id, parent_id=parent_id,
            sample_class="validation", total_samples=total,
            boundaries=boundaries, verdict=verdict, note=note,
        )

    def _boundary(
        self, tag: str, node_items: list[ExecutionEvidence], parent_items: list[ExecutionEvidence]
    ) -> BoundaryResult:
        n = [e for e in node_items if tag in e.fingerprint_tags or tag == "(all)"]
        p = [e for e in parent_items if tag in e.fingerprint_tags or tag == "(all)"]
        ns = sum(1 for e in n if self._success(e))
        ps = sum(1 for e in p if self._success(e))
        nr = ns / len(n) if n else 0.0
        pr = ps / len(p) if p else 0.0
        return BoundaryResult(
            capability_tag=tag,
            node_success=ns, node_total=len(n),
            parent_success=ps, parent_total=len(p),
            node_rate=nr, parent_rate=pr,
            node_ci=wilson_interval(ns, len(n), self.z),
            parent_ci=wilson_interval(ps, len(p), self.z),
            sample_enough=len(n) >= self.min_samples and len(p) >= self.min_samples,
        )

    @staticmethod
    def _success(e: ExecutionEvidence) -> bool:
        if e.status == "error":
            return False
        v = e.verification or {}
        if v:
            return v.get("status") == "verified_success"
        return not e.errors


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 置信区间：小样本稳健，0 样本返回 (0,0)。"""
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))
