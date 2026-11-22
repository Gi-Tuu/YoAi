"""M1 任务指纹与节能路由测试。全部离线、零依赖。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.evolution import (  # noqa: E402
    EvolutionArchive, ExpertRouter, ExpertSpec, fingerprint, normalize, tokenize,
)


# --- 指纹 ---
def test_normalize_is_stable():
    assert normalize("Ｇｅｔ　天气") == "get 天气"
    assert normalize("搜索-查询") == "搜索 查询"
    assert normalize(None) == ""


def test_tokenize_chinese_bigram():
    uni, bi = tokenize("天气")
    assert "天" in uni and "气" in uni
    assert "天气" in bi


def test_fingerprint_is_deterministic():
    a = fingerprint("写一个总结")
    b = fingerprint("写一个总结")
    assert a.key == b.key
    assert a.to_dict() == b.to_dict()


def test_fingerprint_tags_and_signals():
    fp = fingerprint("先搜索资料，然后写一份总结")
    assert "research" in fp.tags
    assert "writing" in fp.tags
    assert "multi_step" in fp.signals


def test_fingerprint_custom_lexicon():
    fp = fingerprint("处理发票", tag_lexicon={"finance": ("发票", "报销")})
    assert "finance" in fp.tags


# --- 路由 ---
def _archive_with_root_and_experts(tmp_path):
    ar = EvolutionArchive(tmp_path / "evo.json")
    root = ar.create_root("通用根", ExpertSpec(capability_tags=("general",)))
    writer = ar.create_child(
        root.id, "写作专家",
        ExpertSpec(tools=("write",), strategy_bias="react", capability_tags=("writing",)),
    )
    ar.transition(writer.id, "probation")
    ar.transition(writer.id, "active")
    coder = ar.create_child(
        root.id, "代码专家",
        ExpertSpec(tools=("code",), capability_tags=("coding",)),
    )
    ar.transition(coder.id, "probation")
    ar.transition(coder.id, "active")
    return ar, root, writer, coder


def test_route_selects_matching_active_expert(tmp_path):
    ar, root, writer, coder = _archive_with_root_and_experts(tmp_path)
    router = ExpertRouter(ar)
    decision = router.route("帮我写一份总结")
    assert decision.selected_id == writer.id
    assert decision.fallback is False
    assert "writing" in decision.reason
    assert decision.scores[writer.id] > 0
    assert router.last_decision == decision


def test_route_falls_back_to_root_when_no_match(tmp_path):
    ar, root, writer, coder = _archive_with_root_and_experts(tmp_path)
    router = ExpertRouter(ar)
    # "你好" 只命中 chat 标签，没有 active 专家声明 chat
    decision = router.route("你好")
    assert decision.selected_id == root.id
    assert decision.fallback is True
    assert "回退" in decision.reason


def test_non_active_expert_not_selected(tmp_path):
    ar, root, writer, coder = _archive_with_root_and_experts(tmp_path)
    # 把写作专家 retired
    ar.transition(writer.id, "retired")
    router = ExpertRouter(ar)
    decision = router.route("帮我写一份总结")
    assert decision.selected_id == root.id
    assert decision.fallback is True
    assert writer.id not in [n.id for n in ar.routing_candidates()]


def test_candidate_expert_not_selected(tmp_path):
    ar, root, writer, coder = _archive_with_root_and_experts(tmp_path)
    # 新建一个 candidate 写作专家（未晋升）
    candidate = ar.create_child(
        root.id, "候选写作", ExpertSpec(tools=("write",), capability_tags=("writing",)),
    )
    router = ExpertRouter(ar)
    decision = router.route("写文案")
    assert decision.selected_id != candidate.id


def test_route_fails_when_no_root(tmp_path):
    ar = EvolutionArchive(tmp_path / "empty.json")
    router = ExpertRouter(ar)
    decision = router.route("写总结")
    assert decision.selected_id is None
    assert "路由失败" in decision.reason


def test_route_decision_is_auditable(tmp_path):
    ar, root, writer, coder = _archive_with_root_and_experts(tmp_path)
    router = ExpertRouter(ar)
    decision = router.route("写摘要")
    d = decision.to_dict()
    for key in ("task", "fingerprint", "selected_id", "scores", "reason", "fallback", "mode"):
        assert key in d
    assert d["fingerprint"]["key"]
    assert d["mode"] == "efficient"


def test_max_performance_mode_is_stub(tmp_path):
    ar, *_ = _archive_with_root_and_experts(tmp_path)
    router = ExpertRouter(ar, mode="max_performance")
    with pytest.raises(NotImplementedError, match="M3"):
        router.route("写总结")


def test_unknown_mode_rejected(tmp_path):
    ar = EvolutionArchive(tmp_path / "evo.json")
    with pytest.raises(ValueError):
        ExpertRouter(ar, mode="bogus")


def test_strategy_bias_uses_signals(tmp_path):
    """策略偏好（plan↔multi_step）能加分，影响选中。"""
    ar = EvolutionArchive(tmp_path / "evo.json")
    root = ar.create_root("root", ExpertSpec())
    planner = ar.create_child(
        root.id, "规划专家",
        ExpertSpec(strategy_bias="plan", capability_tags=("writing",)),
    )
    ar.transition(planner.id, "probation")
    ar.transition(planner.id, "active")
    router = ExpertRouter(ar)
    decision = router.route("先写大纲然后写总结")
    assert decision.selected_id == planner.id
