"""R3.2 试用与批准守护测试：trial 隔离、人工批准、拒绝退役。"""

from __future__ import annotations

from yoai.evidence import (
    EvidenceStore, ExecutionEvidence, FeedbackSignal, FeedbackStore,
    SAMPLE_TRIAL, build_boundary_report,
)
from yoai.evolution import (
    EvolutionArchive, EvolutionReportStore, ExpertSpec, TrialController, TrialStore,
)


def _fixture(tmp_path):
    ev = EvidenceStore(tmp_path / "evidence.json")
    fb = FeedbackStore(tmp_path)
    ar = EvolutionArchive(tmp_path / "evolution.json")
    reports = EvolutionReportStore(tmp_path)
    trials = TrialStore(tmp_path)
    root = ar.create_root("root", ExpertSpec())
    child = ar.create_child(root.id, "candidate",
                            ExpertSpec(tools=("events_between",)),
                            diff={"dimension": "tools", "tag": "temporal"})
    ar.transition(child.id, "probation")
    return ev, fb, ar, reports, trials, root, child


def _trial_items(ev, fb, trial_id, child_id, parent_id,
                 child_ok=20, parent_ok=16, child_rework=2, parent_rework=2):
    for role, expert_id, ok_count, rework_count in (
        ("child", child_id, child_ok, child_rework),
        ("parent", parent_id, parent_ok, parent_rework),
    ):
        for i in range(20):
            ok = i < ok_count
            e = ExecutionEvidence.create(
                session_id="s1", task=f"{role}-{i}",
                task_fingerprint=f"fp-{i}", fingerprint_tags=("temporal",),
                sample_class=SAMPLE_TRIAL, expert_id=expert_id,
                parent_id=parent_id, trial_id=trial_id, trial_role=role,
                status="ok" if ok else "error",
                verification={"status": "verified_success" if ok else "verified_failure"},
                usage={"total_tokens": 1000},
            )
            ev.add(e)
            if i < rework_count:
                fb.add(FeedbackSignal(id=f"f-{role}-{i}", evidence_id=e.id,
                                      run_id=f"r-{role}-{i}", session_id="s1",
                                      kind="regenerate", polarity=-1,
                                      fingerprint_tags=("temporal",)))


def test_trial_report_and_approval(tmp_path):
    ev, fb, ar, reports, trials, root, child = _fixture(tmp_path)
    controller = TrialController(ar, ev, fb, reports, trials)
    record = controller.start(child.id, "tag:temporal", 20)
    _trial_items(ev, fb, record.id, child.id, root.id)

    report = controller.report(record.id)
    assert report.passed and report.child_samples == 20 and report.parent_samples == 20
    validation = [e for e in ev.query(sample_class=SAMPLE_TRIAL)]
    assert len(validation) == 40
    assert build_boundary_report(ev, fb).total == 0  # trial 不进 R1 看板

    approved = controller.approve(record.id, "tester", "通过")
    assert approved.passed
    assert ar.get(child.id).lifecycle == "active"
    assert controller.trials.get(record.id).status == "approved"
    assert any(r.get("kind") == "rsi_approval" for r in reports.list())


def test_approval_requires_human_and_hard_gate(tmp_path):
    ev, fb, ar, reports, trials, root, child = _fixture(tmp_path)
    controller = TrialController(ar, ev, fb, reports, trials)
    record = controller.start(child.id, "tag:temporal", 20)
    _trial_items(ev, fb, record.id, child.id, root.id, child_ok=5, parent_ok=18)

    report = controller.report(record.id)
    assert not report.passed and "成功率下降" in report.reason
    try:
        controller.approve(record.id, "tester")
        raise AssertionError("硬门槛未通过时应拒绝批准")
    except ValueError:
        pass
    assert ar.get(child.id).lifecycle == "probation"

    controller.reject(record.id, "人工拒绝")
    assert ar.get(child.id).lifecycle == "retired"
