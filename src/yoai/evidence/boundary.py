"""能力边界看板（RSI R1）：聚合真实执行证据 + R0 用户反馈。

只做统计与可视化，不触发进化、不写进化档案。
成功判据与 BenchmarkLab 一致；返工判据来自 R0 负向反馈信号。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from yoai.evidence.benchmark_lab import wilson_interval
from yoai.evidence.feedback import FeedbackStore
from yoai.evidence.models import ExecutionEvidence, FeedbackSignal, SAMPLE_EVOLUTION
from yoai.evidence.store import EvidenceStore

# 常见比例监控阈值（定版 v1）
# - 比例估计需要至少 20 个样本才下结论（Wilson 区间半宽约 ≤18pp @ p=0.5）
# - 实际显著性 10pp：薄弱要求区间上界仍低于基线 10pp，避免小样本误判
# - 返工率 15% 进观察、25% 进薄弱，沿用常见 SLO 的警告/严重两档
MIN_SAMPLES = 20
WATCH_GAP = 0.05
WEAK_GAP = 0.10
WATCH_REWORK = 0.15
WEAK_REWORK = 0.25


@dataclass
class BoundaryRow:
    tag: str
    total: int
    success: int
    success_rate: float
    success_ci: tuple[float, float]
    rework: int
    rework_rate: float
    avg_tokens: int
    positive: int
    baseline_gap: float
    status: str
    sample_enough: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag, "total": self.total, "success": self.success,
            "success_rate": round(self.success_rate, 4),
            "success_ci": [round(self.success_ci[0], 4), round(self.success_ci[1], 4)],
            "rework": self.rework, "rework_rate": round(self.rework_rate, 4),
            "avg_tokens": self.avg_tokens, "positive": self.positive,
            "baseline_gap": round(self.baseline_gap, 4),
            "status": self.status, "sample_enough": self.sample_enough,
        }


@dataclass
class BoundaryReport:
    window_days: int
    total: int
    success: int
    success_rate: float
    rework: int
    rework_rate: float
    rows: list[BoundaryRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.window_days, "total": self.total,
            "success": self.success, "success_rate": round(self.success_rate, 4),
            "rework": self.rework, "rework_rate": round(self.rework_rate, 4),
            "rows": [r.to_dict() for r in self.rows],
        }


def _success(evidence: ExecutionEvidence) -> bool:
    if evidence.status == "error":
        return False
    verification = evidence.verification or {}
    if verification:
        return verification.get("status") == "verified_success"
    return not evidence.errors


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


def build_boundary_report(
    evidence_store: EvidenceStore,
    feedback_store: FeedbackStore,
    *,
    window_days: int = 30,
) -> BoundaryReport:
    """按能力标签聚合；返回总览与每行统计。"""
    now = datetime.now(timezone.utc)
    evidence = [e for e in evidence_store.query(sample_class=SAMPLE_EVOLUTION)
                if _in_window(e.created_at, window_days, now)]
    feedback = [s for s in feedback_store.list()
                if _in_window(s.created_at, window_days, now)]
    by_evidence: dict[str, list[FeedbackSignal]] = {}
    for signal in feedback:
        by_evidence.setdefault(signal.evidence_id, []).append(signal)

    total = len(evidence)
    success_total = sum(1 for e in evidence if _success(e))
    rework_total = sum(1 for e in evidence
                       if any(s.polarity < 0 for s in by_evidence.get(e.id, [])))
    baseline = success_total / total if total else 0.0

    buckets: dict[str, list[ExecutionEvidence]] = {}
    for item in evidence:
        tags = item.fingerprint_tags or ("(untagged)",)
        for tag in tags:
            buckets.setdefault(tag, []).append(item)

    rows: list[BoundaryRow] = []
    for tag, items in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        successes = sum(1 for e in items if _success(e))
        rate = successes / len(items)
        rework = sum(1 for e in items
                     if any(s.polarity < 0 for s in by_evidence.get(e.id, [])))
        positive = sum(1 for e in items
                       if any(s.polarity > 0 for s in by_evidence.get(e.id, [])))
        ci = wilson_interval(successes, len(items))
        avg_tokens = int(sum(int(e.usage.get("total_tokens", 0) or 0)
                             for e in items) / len(items))
        gap = rate - baseline
        enough = len(items) >= MIN_SAMPLES
        if not enough:
            status = "insufficient"
        elif ci[1] < baseline - WEAK_GAP or rework / len(items) >= WEAK_REWORK:
            status = "weak"
        elif gap <= -WATCH_GAP or rework / len(items) >= WATCH_REWORK:
            status = "watch"
        else:
            status = "healthy"
        rows.append(BoundaryRow(
            tag=tag, total=len(items), success=successes, success_rate=rate,
            success_ci=ci, rework=rework, rework_rate=rework / len(items),
            avg_tokens=avg_tokens, positive=positive, baseline_gap=gap, status=status,
            sample_enough=enough,
        ))

    return BoundaryReport(
        window_days=window_days, total=total, success=success_total,
        success_rate=baseline, rework=rework_total,
        rework_rate=rework_total / total if total else 0.0, rows=rows,
    )
