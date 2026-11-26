"""R2.2 隔离验证器守护测试：只判定，不晋升。"""

from __future__ import annotations

from yoai.evidence import EvidenceStore, ExecutionEvidence, SAMPLE_VALIDATION
from yoai.evolution import (
    CandidateValidator,
    EvolutionArchive,
    EvolutionReportStore,
    ExpertSpec,
)


def _validation_item(store: EvidenceStore, expert_id: str, parent_id: str,
                     tag: str, n: int, ok: int) -> None:
    for i in range(n):
        good = i < ok
        store.add(ExecutionEvidence.create(
            session_id="s1", task=f"{tag}-{expert_id}-{i}",
            task_fingerprint=f"{tag}-{i}", fingerprint_tags=(tag,),
            sample_class=SAMPLE_VALIDATION, expert_id=expert_id, parent_id=parent_id,
            status="ok" if good else "error",
            verification={"status": "verified_success" if good else "verified_failure"},
        ))


def test_validation_reports_improved_without_promotion(tmp_path):
    ev = EvidenceStore(tmp_path / "evidence.json")
    ar = EvolutionArchive(tmp_path / "evolution.json")
    reports = EvolutionReportStore(tmp_path)
    root = ar.create_root("root", ExpertSpec(tools=("list_facts",)))
    child = ar.create_child(root.id, "candidate", ExpertSpec(tools=("events_between",)))
    _validation_item(ev, child.id, root.id, "temporal", 8, 7)
    _validation_item(ev, root.id, "", "temporal", 8, 2)

    result = CandidateValidator(ar, ev, reports).validate(child.id)
    assert result.verdict == "improved" and result.promoted is False
    assert result.child_validation == 8 and result.parent_validation == 8
    assert ar.get(child.id).lifecycle == "candidate"
    assert any(r.get("kind") == "rsi_validation" for r in reports.list())


def test_validation_without_samples_is_insufficient(tmp_path):
    ev = EvidenceStore(tmp_path / "evidence.json")
    ar = EvolutionArchive(tmp_path / "evolution.json")
    reports = EvolutionReportStore(tmp_path)
    root = ar.create_root("root", ExpertSpec())
    child = ar.create_child(root.id, "candidate", ExpertSpec())
    result = CandidateValidator(ar, ev, reports).validate(child.id)
    assert result.verdict == "insufficient" and "样本不足" in result.note
