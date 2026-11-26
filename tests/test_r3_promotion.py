"""R3.1 晋升器守护测试：improved 只进 probation，绝不 active。"""

from __future__ import annotations

from yoai.evidence import EvidenceStore, ExecutionEvidence, SAMPLE_VALIDATION
from yoai.evolution import (
    CandidateValidation,
    EvolutionArchive,
    EvolutionReportStore,
    ExpertSpec,
    R3Promoter,
)


def _validation(node_id: str, parent_id: str, verdict: str,
                child_tokens: int = 1000, parent_tokens: int = 1000) -> CandidateValidation:
    return CandidateValidation(
        node_id=node_id, parent_id=parent_id, verdict=verdict,
        note="测试", total_samples=8, child_validation=8, parent_validation=8,
        report={"total_samples": 8, "boundaries": [{
            "capability_tag": "temporal", "node_total": 8, "parent_total": 8,
            "node_rate": 0.875, "parent_rate": 0.375,
            "node_ci": [0.5, 0.98], "parent_ci": [0.15, 0.7],
            "sample_enough": True,
        }]},
        promoted=False,
    )


def _fixture(tmp_path, child_tokens=1000, parent_tokens=1000):
    ev = EvidenceStore(tmp_path / "evidence.json")
    ar = EvolutionArchive(tmp_path / "evolution.json")
    reports = EvolutionReportStore(tmp_path)
    root = ar.create_root("root", ExpertSpec())
    child = ar.create_child(
        root.id, "candidate",
        ExpertSpec(tools=("events_between",)),
        diff={"dimension": "tools", "tag": "temporal"},
    )
    for expert_id, tokens in ((child.id, child_tokens), (root.id, parent_tokens)):
        for i in range(8):
            ev.add(ExecutionEvidence.create(
                session_id="s1", task=f"{expert_id}-{i}",
                task_fingerprint=f"fp-{i}", fingerprint_tags=("temporal",),
                sample_class=SAMPLE_VALIDATION, expert_id=expert_id,
                parent_id=root.id,
                status="ok", verification={"status": "verified_success"},
                usage={"total_tokens": tokens},
            ))
    return ev, ar, reports, root, child


def test_improved_promotes_to_probation_only(tmp_path):
    ev, ar, reports, root, child = _fixture(tmp_path)
    decision = R3Promoter(ar, ev, reports).apply(
        _validation(child.id, root.id, "improved"))
    assert decision.changed and decision.to_state == "probation"
    assert ar.get(child.id).lifecycle == "probation"
    assert ar.get(child.id).lifecycle != "active"
    assert any(r.get("kind") == "rsi_promotion" for r in reports.list())


def test_regression_retires_candidate(tmp_path):
    ev, ar, reports, root, child = _fixture(tmp_path)
    decision = R3Promoter(ar, ev, reports).apply(
        _validation(child.id, root.id, "regression"))
    assert decision.changed and decision.to_state == "retired"
    assert ar.get(child.id).lifecycle == "retired"


def test_no_regression_or_cost_guard_keeps_candidate(tmp_path):
    ev, ar, reports, root, child = _fixture(tmp_path)
    promoter = R3Promoter(ar, ev, reports)
    assert promoter.apply(_validation(child.id, root.id, "no_regression")).to_state == "candidate"
    assert ar.get(child.id).lifecycle == "candidate"

    ev2, ar2, reports2, root2, child2 = _fixture(tmp_path / "cost", 2000, 1000)
    decision = R3Promoter(ar2, ev2, reports2).apply(
        _validation(child2.id, root2.id, "improved"))
    assert not decision.changed and "成本守卫" in decision.reason
    assert ar2.get(child2.id).lifecycle == "candidate"
