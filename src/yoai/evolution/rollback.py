"""R3.3 active 回归监控与自动回滚（YoAi 侧，内核零改动）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from yoai.evidence.benchmark_lab import wilson_interval
from yoai.evidence.feedback import FeedbackStore
from yoai.evidence.models import SAMPLE_EVOLUTION
from yoai.evidence.store import EvidenceStore
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.reports import EvolutionReportStore

MIN_MONITOR_SAMPLES = 5
CI_TOLERANCE = 0.05
REWORK_ABSOLUTE = 0.25
REWORK_DELTA = 0.05
COST_RATIO = 1.20


@dataclass
class RollbackDecision:
    node_id: str
    rolled_back: bool
    reason: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "rolled_back": self.rolled_back,
                "reason": self.reason, "detail": self.detail}


def _in_window(created_at: str, days: int, now: datetime) -> bool:
    if not created_at:
        return True
    try:
        moment = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment >= now - timedelta(days=days)


class RollbackMonitor:
    def __init__(
        self,
        archive: EvolutionArchive,
        evidence_store: EvidenceStore,
        feedback_store: FeedbackStore,
        report_store: EvolutionReportStore,
    ) -> None:
        self.archive = archive
        self.store = evidence_store
        self.feedback = feedback_store
        self.reports = report_store

    def check(self, node_id: str, *, window_days: int = 30) -> RollbackDecision:
        node = self.archive.get(node_id)
        if node is None or node.lifecycle != "active":
            return RollbackDecision(node_id, False, "节点非 active，跳过", {})
        parent = self.archive.get(node.parent_id or "")
        if parent is None:
            return RollbackDecision(node_id, False, "父节点不存在，跳过", {})

        now = datetime.now(timezone.utc)
        items = [e for e in self.store.query(sample_class=SAMPLE_EVOLUTION)
                 if _in_window(e.created_at, window_days, now)]
        child = [e for e in items if e.expert_id == node_id]
        p_items = [e for e in items if e.expert_id == parent.id]
        if len(child) < MIN_MONITOR_SAMPLES:
            return RollbackDecision(node_id, False,
                                    f"active 样本不足 {MIN_MONITOR_SAMPLES}", {})

        def rate(rows) -> tuple[int, float]:
            ok = sum(1 for e in rows
                     if (e.verification or {}).get("status") == "verified_success")
            return ok, ok / len(rows) if rows else 0.0
        c_ok, c_rate = rate(child)
        p_ok, p_rate = rate(p_items)
        c_ci = wilson_interval(c_ok, len(child))
        p_ci = wilson_interval(p_ok, len(p_items)) if p_items else (0.0, 0.0)

        negatives = {s.evidence_id for s in self.feedback.list() if s.polarity < 0}
        c_rework = sum(1 for e in child if e.id in negatives) / len(child)
        p_rework = (sum(1 for e in p_items if e.id in negatives) / len(p_items)
                    if p_items else 0.0)
        failures = sum(1 for e in child
                       if (e.verification or {}).get("status") == "verified_failure")
        c_tokens = sum(int(e.usage.get("total_tokens", 0) or 0) for e in child) / len(child)
        p_tokens = (sum(int(e.usage.get("total_tokens", 0) or 0) for e in p_items)
                    / len(p_items) if p_items else 0.0)

        detail = {
            "child_samples": len(child), "parent_samples": len(p_items),
            "child_rate": round(c_rate, 4), "parent_rate": round(p_rate, 4),
            "child_ci": [round(v, 4) for v in c_ci],
            "parent_ci": [round(v, 4) for v in p_ci],
            "child_rework": round(c_rework, 4), "parent_rework": round(p_rework, 4),
            "verified_failures": failures,
            "child_tokens": int(c_tokens), "parent_tokens": int(p_tokens),
        }
        reasons = []
        if c_ci[0] < p_ci[0] - CI_TOLERANCE:
            reasons.append("成功率置信下界低于父节点超过 5pp")
        if c_rework >= REWORK_ABSOLUTE and c_rework > p_rework + REWORK_DELTA:
            reasons.append("返工率超过 25% 且高于父节点 5pp")
        if failures:
            reasons.append(f"verified_failure={failures}")
        if p_tokens > 0 and c_tokens > p_tokens * COST_RATIO and c_rate <= p_rate + 0.02:
            reasons.append("成本超过父节点 20% 且无准确率收益")

        if not reasons:
            return RollbackDecision(node_id, False, "未触发回滚", detail)

        self.archive.transition(node_id, "retired")
        reason = "；".join(reasons)
        self.reports.add({
            "id": f"rollback-{node_id}-{int(now.timestamp())}", "evidence_id": "",
            "triggered": True, "cause": "rsi_rollback", "new_node_id": node_id,
            "reason": f"{reason}；回退到 {parent.id}",
            "created_at": now.isoformat(), "kind": "rsi_rollback",
            "rollback_to": parent.id, "detail": detail,
        })
        return RollbackDecision(node_id, True, reason, detail)
