"""R2.1 shadow 触发引擎守护测试：能生成候选，但不晋升、不重复触发。"""

from __future__ import annotations

from yoai.evidence import (
    Attribution,
    EvidenceStore,
    ExecutionEvidence,
    FeedbackSignal,
    FeedbackStore,
    build_boundary_report,
)
from yoai.evolution import EvolutionArchive, EvolutionReportStore, ExpertSpec, TriggerEngine


def _fixture(tmp_path):
    ev = EvidenceStore(tmp_path / "evidence.json")
    fb = FeedbackStore(tmp_path)
    ar = EvolutionArchive(tmp_path / "evolution" / "evolution.json")
    root = ar.create_root("root", ExpertSpec(tools=("list_facts",), capability_tags=("root",)))
    for i in range(20):
        ok = i < 12
        e = ExecutionEvidence.create(
            session_id="s1", task=f"任务{i}", task_fingerprint=f"fp{i}",
            fingerprint_tags=("temporal",), expert_id=root.id,
            status="ok" if ok else "error",
            verification={"status": "verified_success" if ok else "verified_failure"},
            tool_calls=("events_between",), usage={"total_tokens": 1000},
        )
        ev.add(e)
        ev.add_attribution(Attribution(
            evidence_id=e.id, cause="capability", confidence=0.8,
            reason="测试能力归因"))
        if i < 5:
            fb.add(FeedbackSignal(
                id=f"f{i}", evidence_id=e.id, run_id=f"r{i}", session_id="s1",
                kind="regenerate", polarity=-1, task_fingerprint=f"fp{i}",
                fingerprint_tags=("temporal",),
            ))
    return ev, fb, ar, EvolutionReportStore(tmp_path), root


def test_trigger_creates_candidate_once(tmp_path):
    ev, fb, ar, reports, root = _fixture(tmp_path)
    report = build_boundary_report(ev, fb)
    assert next(r for r in report.rows if r.tag == "temporal").status == "weak"

    engine = TriggerEngine(ar, ev, reports)
    decisions = engine.evaluate(report)
    temporal = next(d for d in decisions if d.tag == "temporal")
    assert temporal.created and temporal.node_id

    node = ar.get(temporal.node_id)
    assert node and node.lifecycle == "candidate" and node.parent_id == root.id
    assert "events_between" in node.spec.tools
    assert node.spec.prompt_suffix == root.spec.prompt_suffix
    assert len(reports.list()) == 1

    again = [d for d in engine.evaluate(report) if d.tag == "temporal"]
    assert not again[0].created and "冷却" in again[0].reason
    assert len(reports.list()) == 1


def test_trigger_skips_watch_boundary(tmp_path):
    ev, fb, ar, reports, root = _fixture(tmp_path)
    report = build_boundary_report(ev, fb)
    row = next(r for r in report.rows if r.tag == "temporal")
    row.status = "watch"
    decisions = TriggerEngine(ar, ev, reports).evaluate(report)
    assert not decisions[0].created
    assert ar.list_nodes() == [root]
