"""R2.2 候选隔离验证器（YoAi 侧，内核零改动）。

对 candidate 节点与其 parent 使用 held-out validation 证据跑 BenchmarkLab 成对判定。
本阶段只产出验证报告和 verdict，**不做晋升、不改生命周期**——晋升属于 R3。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoai.evidence.benchmark_lab import BenchmarkLab
from yoai.evidence.models import SAMPLE_VALIDATION
from yoai.evidence.store import EvidenceStore
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.reports import EvolutionReportStore


@dataclass
class CandidateValidation:
    node_id: str
    parent_id: str
    verdict: str
    note: str
    total_samples: int
    child_validation: int
    parent_validation: int
    report: dict[str, Any]
    promoted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "parent_id": self.parent_id,
            "verdict": self.verdict, "note": self.note,
            "total_samples": self.total_samples,
            "child_validation": self.child_validation,
            "parent_validation": self.parent_validation,
            "report": self.report, "promoted": self.promoted,
        }


class CandidateValidator:
    def __init__(
        self,
        archive: EvolutionArchive,
        evidence_store: EvidenceStore,
        report_store: EvolutionReportStore,
    ) -> None:
        self.archive = archive
        self.store = evidence_store
        self.reports = report_store

    def validate(self, node_id: str) -> CandidateValidation:
        node = self.archive.get(node_id)
        if node is None:
            return self._failed(node_id, "", "候选节点不存在")
        if node.lifecycle != "candidate":
            return self._failed(node_id, node.parent_id or "",
                                f"仅 candidate 可验证（当前 {node.lifecycle}）")
        parent_id = node.parent_id or ""
        if not parent_id or self.archive.get(parent_id) is None:
            return self._failed(node_id, parent_id, "父节点不存在，无法成对验证")

        validation = self.store.query(sample_class=SAMPLE_VALIDATION)
        child_items = [e for e in validation if e.expert_id == node_id]
        parent_items = [e for e in validation if e.expert_id == parent_id]
        if not child_items or not parent_items:
            return self._failed(
                node_id, parent_id,
                f"隔离验证样本不足：child={len(child_items)} parent={len(parent_items)}",
                len(child_items), len(parent_items),
            )

        report = BenchmarkLab(self.store).evaluate(node_id, parent_id)
        result = CandidateValidation(
            node_id=node_id, parent_id=parent_id,
            verdict=report.verdict, note=report.note,
            total_samples=report.total_samples,
            child_validation=len(child_items), parent_validation=len(parent_items),
            report=report.to_dict(), promoted=False,
        )
        self.reports.add({
            "id": f"val-{node_id}", "evidence_id": "", "triggered": True,
            "cause": "rsi_isolation_validation", "new_node_id": node_id,
            "reason": f"{report.verdict}: {report.note}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "rsi_validation", "verdict": report.verdict,
        })
        return result

    def _failed(
        self, node_id: str, parent_id: str, reason: str,
        child: int = 0, parent: int = 0,
    ) -> CandidateValidation:
        return CandidateValidation(
            node_id=node_id, parent_id=parent_id,
            verdict="insufficient", note=reason, total_samples=child,
            child_validation=child, parent_validation=parent,
            report={"verdict": "insufficient", "note": reason,
                    "total_samples": child, "boundaries": []},
            promoted=False,
        )
