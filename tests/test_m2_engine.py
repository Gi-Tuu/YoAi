"""M2 进化链测试：候选生成、隔离评测晋升、退化保留、审计。全部离线。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.evidence import (  # noqa: E402
    ATTRIBUTION_CAPABILITY, ATTRIBUTION_ENVIRONMENT,
    ATTRIBUTION_NONE, SAMPLE_VALIDATION,
    Attribution, EvidenceStore, ExecutionEvidence,
)
from yoai.evolution import (  # noqa: E402
    EvolutionArchive, EvolutionEngine, ExpertSpec,
)


def _setup(tmp_path):
    ar = EvolutionArchive(tmp_path / "evo.json")
    root = ar.create_root("root", ExpertSpec())
    store = EvidenceStore(tmp_path / "ev.json")
    return ar, root, store


def _evidence(eid, expert, *, fingerprint="fp", tags=("writing",), tools=(),
              sample=SAMPLE_VALIDATION, verification=None):
    return ExecutionEvidence.create(
        id=eid, session_id="s", task="写总结", task_fingerprint=fingerprint,
        fingerprint_tags=tags, sample_class=sample, expert_id=expert,
        parent_id=None, strategy="react", status="ok", tool_calls=tools,
        verification=verification,
    )


def _save_attribution(store, eid, cause):
    a = Attribution(evidence_id=eid, cause=cause, confidence=0.8, reason=f"test {cause}")
    store.add_attribution(a)
    return a


# --- 不进化 ---
def test_success_does_not_evolve(tmp_path):
    ar, root, store = _setup(tmp_path)
    ev = _evidence("e1", root.id, verification={"status": "verified_success"})
    store.add(ev); _save_attribution(store, "e1", ATTRIBUTION_NONE)
    report = EvolutionEngine(ar, store).evolve("e1")
    assert report.triggered is False and report.cause == ATTRIBUTION_NONE
    assert ar.count() == 1  # 没造分支


def test_environment_problem_does_not_evolve(tmp_path):
    """环境问题改专家没用 —— 不产生无意义分支（设计单核心）。"""
    ar, root, store = _setup(tmp_path)
    ev = _evidence("e1", root.id, verification={"status": "verified_failure"})
    store.add(ev); _save_attribution(store, "e1", ATTRIBUTION_ENVIRONMENT)
    report = EvolutionEngine(ar, store).evolve("e1")
    assert report.triggered is False and report.cause == ATTRIBUTION_ENVIRONMENT
    assert ar.count() == 1


def test_missing_evidence_no_evolve(tmp_path):
    ar, root, store = _setup(tmp_path)
    report = EvolutionEngine(ar, store).evolve("nope")
    assert report.triggered is False and report.cause == "missing"


# --- 能力问题 → 候选 ---
def test_capability_creates_candidate_from_executing_node(tmp_path):
    ar, root, store = _setup(tmp_path)
    # 造一个已 active 的专家作为实际执行节点
    child = ar.create_child(root.id, "writer", ExpertSpec(capability_tags=("writing",)))
    ar.transition(child.id, "probation"); ar.transition(child.id, "active")
    ev = _evidence("e1", child.id, tools=("remember_fact",),
                   verification={"status": "verified_failure"})
    store.add(ev); _save_attribution(store, "e1", ATTRIBUTION_CAPABILITY)
    report = EvolutionEngine(ar, store).evolve("e1")
    assert report.triggered is True and report.cause == ATTRIBUTION_CAPABILITY
    assert report.proposal.parent_id == child.id  # 从实际执行节点派生，不是根
    new = ar.get(report.new_node_id)
    assert new.parent_id == child.id and new.lifecycle == "candidate"
    assert "remember_fact" in new.spec.tools  # 补了工具
    assert "核对实际状态" in new.spec.prompt_suffix  # 补了提示


def test_routing_problem_adds_capability_tags(tmp_path):
    ar, root, store = _setup(tmp_path)
    ev = _evidence("e1", root.id, tags=("coding",),
                   verification={"status": "verified_failure"})
    store.add(ev); _save_attribution(store, "e1", "routing")
    report = EvolutionEngine(ar, store).evolve("e1")
    assert report.triggered is True
    new = ar.get(report.new_node_id)
    assert "coding" in new.spec.capability_tags  # 补标签让下次能选中


# --- 隔离评测晋升 ---
def test_insufficient_validation_samples_no_promotion(tmp_path):
    ar, root, store = _setup(tmp_path)
    ev = _evidence("e1", root.id, verification={"status": "verified_failure"})
    store.add(ev); _save_attribution(store, "e1", ATTRIBUTION_CAPABILITY)
    engine = EvolutionEngine(ar, store)
    report = engine.evolve("e1")
    # 没有 validation 样本对照 → 评测 insufficient → 不晋升
    assert report.promotion.promoted is False
    assert "insufficient" in report.promotion.reason or "样本" in report.promotion.reason
    assert ar.get(report.new_node_id).lifecycle == "candidate"


def test_improved_promotes_to_probation(tmp_path):
    ar, root, store = _setup(tmp_path)
    # 先准备验证样本：候选(用 root.id 作为 expert 占位) vs 父节点，4 条对照
    # 注意：候选节点 id 事后才知道，这里用"评测时新节点已在 validation 样本里"的方式
    # 由于 evolve 才创建节点，直接测 PromotionGate 更清晰
    from yoai.evolution.promotion import PromotionGate

    cand = ar.create_child(root.id, "cand", ExpertSpec())
    for i in range(4):
        store.add(_evidence(f"c{i}", cand.id, verification={"status": "verified_success"}))
        store.add(_evidence(f"p{i}", root.id, verification={"status": "verified_failure"}))
    decision = PromotionGate(ar, store).evaluate_probation(cand.id, root.id)
    assert decision.promoted is True and decision.to_state == "probation"
    assert ar.get(cand.id).lifecycle == "probation"


def test_regression_keeps_candidate(tmp_path):
    from yoai.evolution.promotion import PromotionGate

    ar, root, store = _setup(tmp_path)
    cand = ar.create_child(root.id, "cand", ExpertSpec())
    for i in range(4):
        store.add(_evidence(f"c{i}", cand.id, verification={"status": "verified_failure"}))
        store.add(_evidence(f"p{i}", root.id, verification={"status": "verified_success"}))
    decision = PromotionGate(ar, store).evaluate_probation(cand.id, root.id)
    assert decision.promoted is False
    assert ar.get(cand.id).lifecycle == "candidate"


# --- 试用晋升 active ---
def test_probation_to_active_needs_trial_samples(tmp_path):
    from yoai.evolution.promotion import PromotionGate

    ar, root, store = _setup(tmp_path)
    cand = ar.create_child(root.id, "cand", ExpertSpec())
    ar.transition(cand.id, "probation")
    gate = PromotionGate(ar, store, min_trial_samples=2)
    d1 = gate.evaluate_active(cand.id)
    assert d1.promoted is False  # 无试用样本
    store.add(_evidence("t1", cand.id, verification={"status": "verified_success"}))
    store.add(_evidence("t2", cand.id, verification={"status": "verified_success"}))
    d2 = gate.evaluate_active(cand.id)
    assert d2.promoted is True and d2.to_state == "active"


def test_trial_failure_blocks_active(tmp_path):
    from yoai.evolution.promotion import PromotionGate

    ar, root, store = _setup(tmp_path)
    cand = ar.create_child(root.id, "cand", ExpertSpec())
    ar.transition(cand.id, "probation")
    gate = PromotionGate(ar, store, min_trial_samples=2)
    store.add(_evidence("t1", cand.id, verification={"status": "verified_failure"}))
    store.add(_evidence("t2", cand.id, verification={"status": "verified_success"}))
    assert gate.evaluate_active(cand.id).promoted is False


def test_retire_on_regression(tmp_path):
    from yoai.evolution.promotion import PromotionGate

    ar, root, store = _setup(tmp_path)
    cand = ar.create_child(root.id, "cand", ExpertSpec())
    ar.transition(cand.id, "probation"); ar.transition(cand.id, "active")
    for i in range(4):
        store.add(_evidence(f"c{i}", cand.id, verification={"status": "verified_failure"}))
        store.add(_evidence(f"p{i}", root.id, verification={"status": "verified_success"}))
    decision = PromotionGate(ar, store).retire_if_regressed(cand.id, root.id)
    assert decision.promoted is True and decision.to_state == "retired"
    assert ar.get(cand.id).lifecycle == "retired"  # 档案保留，退出路由


# --- 审计 ---
def test_reports_persist_and_auditable(tmp_path):
    ar, root, store = _setup(tmp_path)
    ev = _evidence("e1", root.id, verification={"status": "verified_failure"})
    store.add(ev); _save_attribution(store, "e1", ATTRIBUTION_ENVIRONMENT)
    engine = EvolutionEngine(ar, store)
    report = engine.evolve("e1")
    d = report.to_dict()
    for key in ("id", "evidence_id", "triggered", "cause", "reason", "created_at"):
        assert key in d
    store2 = EvidenceStore(tmp_path / "ev.json")
    assert len(store2.evolution_reports()) == 1
    assert store2.status()["reports"] == 1
