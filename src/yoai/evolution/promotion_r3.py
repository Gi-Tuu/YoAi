"""R3.1 晋升器：验证结论 → candidate/probation/retired 状态迁移。

核心口径：improved 只进 probation，不直接 active。
本模块不改 Core、不改路由；probation 仍不参与正常路由。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoai.evidence.models import SAMPLE_VALIDATION
from yoai.evidence.store import EvidenceStore
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.reports import EvolutionReportStore
from yoai.evolution.validation import CandidateValidation

MIN_VALIDATION_SAMPLES = 5
MAX_COST_RATIO = 1.20
ALLOWED_DIMENSIONS = {"tools", "prompt", "capability_tags"}


@dataclass
class R3Decision:
    node_id: str
    from_state: str
    to_state: str
    changed: bool
    reason: str
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "from_state": self.from_state,
                "to_state": self.to_state, "changed": self.changed,
                "reason": self.reason, "verdict": self.verdict}


class R3Promoter:
    def __init__(
        self,
        archive: EvolutionArchive,
        evidence_store: EvidenceStore,
        report_store: EvolutionReportStore,
    ) -> None:
        self.archive = archive
        self.store = evidence_store
        self.reports = report_store

    def apply(self, validation: CandidateValidation) -> R3Decision:
        node = self.archive.get(validation.node_id)
        if node is None:
            return self._decision(validation, node_state="", to="", changed=False,
                                  reason="节点不存在")
        before = node.lifecycle
        if before != "candidate":
            return self._decision(validation, node_state=before, to=before,
                                  changed=False, reason=f"仅 candidate 可晋升（当前 {before}）")

        verdict = validation.verdict
        if verdict == "regression":
            self.archive.transition(node.id, "retired")
            reason = f"隔离验证退化：{validation.note}；保留档案，退出候选池"
            return self._commit(validation, before, "retired", reason)

        if verdict in ("insufficient", "no_regression"):
            reason = f"隔离验证 {verdict}，保持 candidate：{validation.note}"
            return self._commit(validation, before, "candidate", reason)

        if verdict != "improved":
            return self._commit(validation, before, "candidate",
                                f"未知验证结论 {verdict}，保守保持 candidate")

        guard = self._guards(validation)
        if guard:
            return self._commit(validation, before, "candidate", guard)

        self.archive.transition(node.id, "probation")
        reason = (f"隔离验证 improved：{validation.note}；"
                  "自动进入 probation，但不进路由、不直接 active")
        return self._commit(validation, before, "probation", reason)

    def _guards(self, validation: CandidateValidation) -> str:
        node = self.archive.get(validation.node_id)
        assert node is not None
        if node.diff.get("dimension") not in ALLOWED_DIMENSIONS:
            return "候选 diff 不是单维度（tools/prompt/capability_tags），拒绝晋升"
        boundaries = validation.report.get("boundaries") or []
        if not boundaries:
            return "缺少能力边界验证结果，拒绝晋升"
        for boundary in boundaries:
            node_total = int(boundary.get("node_total", 0))
            parent_total = int(boundary.get("parent_total", 0))
            if node_total == 0 and parent_total == 0:
                continue
            # child 未参与的能力标签不构成该候选的验证边界（共享 parent 会带入其他标签）
            if node_total > 0 and node_total < MIN_VALIDATION_SAMPLES:
                return f"child 边界样本不足 {MIN_VALIDATION_SAMPLES}"
            if parent_total > 0 and parent_total < MIN_VALIDATION_SAMPLES:
                return f"parent 边界样本不足 {MIN_VALIDATION_SAMPLES}"
        ratio = self._cost_ratio(validation.node_id, validation.parent_id)
        if ratio is None or ratio > MAX_COST_RATIO:
            shown = "无法计算" if ratio is None else f"{ratio:.2f}"
            return f"成本守卫未通过：token 比 {shown}，上限 {MAX_COST_RATIO}"
        return ""

    def _cost_ratio(self, node_id: str, parent_id: str) -> float | None:
        items = [e for e in self.store.query(sample_class=SAMPLE_VALIDATION)
                 if e.expert_id in (node_id, parent_id)]
        def avg(expert_id: str) -> float:
            values = [int(e.usage.get("total_tokens", 0) or 0)
                      for e in items if e.expert_id == expert_id]
            return sum(values) / len(values) if values else 0.0
        parent = avg(parent_id)
        if parent <= 0:
            return None
        return avg(node_id) / parent

    def _commit(self, validation: CandidateValidation, before: str,
                to: str, reason: str) -> R3Decision:
        self.reports.add({
            "id": f"prom-{validation.node_id}-{int(datetime.now(timezone.utc).timestamp())}",
            "evidence_id": "", "triggered": to != before,
            "cause": "r3_promotion", "new_node_id": validation.node_id,
            "reason": reason, "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "rsi_promotion", "verdict": validation.verdict,
            "from_state": before, "to_state": to,
        })
        return self._decision(validation, before, to, to != before, reason)

    @staticmethod
    def _decision(validation: CandidateValidation, node_state: str, to: str,
                  changed: bool, reason: str) -> R3Decision:
        return R3Decision(validation.node_id, node_state, to, changed,
                          reason, validation.verdict)
