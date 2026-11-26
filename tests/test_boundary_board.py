"""R1 能力边界看板聚合守护测试：只统计，不触发进化。"""

from __future__ import annotations

from yoai.evidence import (
    EvidenceStore,
    ExecutionEvidence,
    FeedbackSignal,
    FeedbackStore,
    build_boundary_report,
)


def test_boundary_report_aggregates_success_and_rework(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    feedback_store = FeedbackStore(tmp_path)
    for i in range(20):
        ok = i < 12
        e = ExecutionEvidence.create(
            session_id="s1", task=f"任务{i}", task_fingerprint=f"fp{i}",
            fingerprint_tags=("temporal",),
            status="ok" if ok else "error",
            verification={"status": "verified_success" if ok else "verified_failure"},
            usage={"total_tokens": 1000},
        )
        evidence_store.add(e)
        if i < 5:
            feedback_store.add(FeedbackSignal(
                id=f"f{i}", evidence_id=e.id, run_id=f"r{i}", session_id="s1",
                kind="regenerate", polarity=-1, task_fingerprint=f"fp{i}",
                fingerprint_tags=("temporal",),
            ))

    report = build_boundary_report(evidence_store, feedback_store)
    assert report.total == 20 and report.success == 12
    assert abs(report.success_rate - 0.6) < 0.01
    row = next(r for r in report.rows if r.tag == "temporal")
    assert row.total == 20 and row.success == 12 and row.rework == 5
    assert row.avg_tokens == 1000
    assert row.sample_enough is True and row.status == "weak"
    assert row.success_ci[0] <= row.success_rate <= row.success_ci[1]


def test_boundary_report_handles_empty_data(tmp_path):
    report = build_boundary_report(EvidenceStore(tmp_path / "e.json"), FeedbackStore(tmp_path))
    assert report.total == 0 and report.rows == []
