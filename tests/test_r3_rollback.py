"""R3.3 回归监控与回滚守护测试。"""

from __future__ import annotations

from yoai.evidence import (
    EvidenceStore, ExecutionEvidence, FeedbackSignal, FeedbackStore, SAMPLE_EVOLUTION,
)
from yoai.evolution import (
    EvolutionArchive, EvolutionReportStore, ExpertSpec, ForcedExpertRouter, RollbackMonitor,
)


def _items(ev, fb, expert_id, parent_id, ok_count, rework_count, tag):
    for i in range(8):
        ok = i < ok_count
        e = ExecutionEvidence.create(
            session_id="s1", task=f"{tag}-{expert_id}-{i}",
            task_fingerprint=f"fp-{i}", fingerprint_tags=(tag,),
            sample_class=SAMPLE_EVOLUTION, expert_id=expert_id, parent_id=parent_id,
            status="ok" if ok else "error",
            verification={"status": "verified_success" if ok else "verified_failure"},
            usage={"total_tokens": 1000},
        )
        ev.add(e)
        if i < rework_count:
            fb.add(FeedbackSignal(id=f"f-{expert_id}-{i}", evidence_id=e.id,
                                  run_id=f"r-{i}", session_id="s1",
                                  kind="regenerate", polarity=-1,
                                  fingerprint_tags=(tag,)))


def test_active_regression_rolls_back(tmp_path):
    ev = EvidenceStore(tmp_path / "evidence.json")
    fb = FeedbackStore(tmp_path)
    ar = EvolutionArchive(tmp_path / "evolution.json")
    reports = EvolutionReportStore(tmp_path)
    root = ar.create_root("root", ExpertSpec())
    child = ar.create_child(root.id, "active", ExpertSpec(),
                            diff={"dimension": "tools", "tag": "temporal"})
    ar.transition(child.id, "probation")
    ar.transition(child.id, "active")
    _items(ev, fb, child.id, root.id, 1, 6, "temporal")
    _items(ev, fb, root.id, "", 7, 1, "temporal")

    decision = RollbackMonitor(ar, ev, fb, reports).check(child.id)
    assert decision.rolled_back and ar.get(child.id).lifecycle == "retired"
    assert any(r.get("kind") == "rsi_rollback" for r in reports.list())


def test_no_rollback_when_healthy(tmp_path):
    ev = EvidenceStore(tmp_path / "evidence.json")
    fb = FeedbackStore(tmp_path)
    ar = EvolutionArchive(tmp_path / "evolution.json")
    reports = EvolutionReportStore(tmp_path)
    root = ar.create_root("root", ExpertSpec())
    child = ar.create_child(root.id, "active", ExpertSpec(),
                            diff={"dimension": "tools", "tag": "temporal"})
    ar.transition(child.id, "probation")
    ar.transition(child.id, "active")
    _items(ev, fb, child.id, root.id, 8, 0, "temporal")
    _items(ev, fb, root.id, "", 7, 1, "temporal")

    decision = RollbackMonitor(ar, ev, fb, reports).check(child.id)
    assert not decision.rolled_back and ar.get(child.id).lifecycle == "active"


def test_forced_router_selects_shadow_parent(tmp_path):
    ar = EvolutionArchive(tmp_path / "evolution.json")
    root = ar.create_root("root", ExpertSpec())
    child = ar.create_child(root.id, "child", ExpertSpec())
    decision = ForcedExpertRouter(ar, root.id).route("任意任务")
    assert decision.selected_id == root.id and "shadow" in decision.reason
    assert ar.get(child.id).parent_id == root.id
