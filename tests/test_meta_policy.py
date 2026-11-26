"""R4 元策略守护测试：版本化、受界提案、人工批准。"""

from __future__ import annotations

from yoai.evolution import EvolutionReportStore, MetaEvolution, MetaPolicyStore


def test_meta_policy_propose_and_approve(tmp_path):
    reports = EvolutionReportStore(tmp_path)
    store = MetaPolicyStore(tmp_path)
    evolution = MetaEvolution(store, reports)

    assert evolution.status()["active"]["version"] == 1
    assert evolution.propose()["created"] is False

    for i in range(3):
        reports.add({"id": f"val-{i}", "kind": "rsi_validation",
                     "verdict": "improved", "created_at": "2026-11-26T00:00:00Z"})
    proposal = evolution.propose()
    assert proposal["created"] is True
    assert proposal["policy"]["version"] == 2
    assert proposal["policy"]["parent_id"] == "meta-v1"
    assert proposal["policy"]["min_trial_samples"] < 20

    approved = evolution.approve(2, "tester")
    assert approved.version == 2
    assert evolution.status()["active"]["version"] == 2
    assert any(r.get("kind") == "rsi_meta_approve" for r in reports.list())


def test_meta_policy_bounds_and_approval_required(tmp_path):
    reports = EvolutionReportStore(tmp_path)
    store = MetaPolicyStore(tmp_path)
    evolution = MetaEvolution(store, reports)
    for i in range(4):
        reports.add({"id": f"rollback-{i}", "kind": "rsi_rollback",
                     "created_at": "2026-11-26T00:00:00Z"})
    reports.add({"id": "promo", "kind": "r3_promotion",
                 "created_at": "2026-11-26T00:00:00Z"})
    proposal = evolution.propose()
    assert proposal["created"] is True
    policy = proposal["policy"]
    assert policy["weak_gap"] <= 0.25
    assert policy["cost_ratio"] >= 1.0
    assert policy["weak_rework"] >= 0.10
    assert store.active().version == 1   # 提案不自动生效
