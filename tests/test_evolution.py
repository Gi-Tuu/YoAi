"""M0 进化档案测试：血统、状态机、恢复点、持久化、损坏隔离。

全部离线、标准库、零依赖。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.evolution import (  # noqa: E402
    Checkpoint, EvidenceRef, EvolutionArchive, ExpertNode, ExpertSpec,
)


def _spec(*tools: str, tags: tuple[str, ...] = ()) -> ExpertSpec:
    return ExpertSpec(tools=tuple(tools), capability_tags=tags, prompt_suffix="能力提示")


def _archive(tmp_path, deps=None) -> EvolutionArchive:
    return EvolutionArchive(tmp_path / "evolution.json", dependencies=deps or {})


# --- 根与子 ---
def test_create_root_is_active_and_reusable(tmp_path):
    ar = _archive(tmp_path, {"core": "0.62.7"})
    root = ar.create_root("通用根", _spec("remember_fact", tags=("general",)))
    assert root.lifecycle == "active"
    assert root.parent_id is None
    assert root.dependencies == {"core": "0.62.7"}
    # 再建一次不重建
    assert ar.create_root("另一个根", _spec()).id == root.id
    assert ar.count() == 1


def test_create_child_keeps_parent_active(tmp_path):
    ar = _archive(tmp_path)
    root = ar.create_root("通用根", _spec(tags=("general",)))
    child = ar.create_child(
        root.id, "写作专家", _spec("remember_fact", tags=("writing",)),
        diff={"tools": ["+remember_fact"]},
    )
    assert child.lifecycle == "candidate"
    assert child.parent_id == root.id
    assert child.diff == {"tools": ["+remember_fact"]}
    # 关键：父节点产生子节点后仍 active、仍可路由
    assert ar.get(root.id).lifecycle == "active"
    assert root.id in [n.id for n in ar.routing_candidates()]


def test_create_child_with_unknown_parent_raises(tmp_path):
    ar = _archive(tmp_path)
    ar.create_root("root", _spec())
    try:
        ar.create_child("nope", "x", _spec())
    except KeyError:
        return
    raise AssertionError("未知父节点应抛 KeyError")


# --- 血统 ---
def test_lineage_and_descendants(tmp_path):
    ar = _archive(tmp_path)
    root = ar.create_root("root", _spec())
    a = ar.create_child(root.id, "A", _spec())
    b = ar.create_child(a.id, "B", _spec())
    c = ar.create_child(a.id, "C", _spec())
    lineage_ids = [n.id for n in ar.lineage(b.id)]
    assert lineage_ids == [root.id, a.id, b.id]
    desc_ids = {n.id for n in ar.descendants(root.id)}
    assert desc_ids == {a.id, b.id, c.id}
    assert ar.children(a.id)[0].id in (b.id, c.id)


# --- 生命周期状态机 ---
def test_lifecycle_forward_only(tmp_path):
    ar = _archive(tmp_path)
    root = ar.create_root("root", _spec())
    child = ar.create_child(root.id, "child", _spec())
    assert child.lifecycle == "candidate"
    # candidate → probation → active → retired
    assert ar.transition(child.id, "probation") is True
    assert ar.transition(child.id, "active") is True
    assert ar.transition(child.id, "retired") is True
    # retired 终态，不可迁移
    assert ar.transition(child.id, "active") is False
    assert ar.get(child.id).lifecycle == "retired"


def test_illegal_lifecycle_transition_rejected(tmp_path):
    ar = _archive(tmp_path)
    root = ar.create_root("root", _spec())
    child = ar.create_child(root.id, "child", _spec())
    # candidate 不能直接 → active
    assert ar.transition(child.id, "active") is False
    assert ar.get(child.id).lifecycle == "candidate"
    # 未知节点
    assert ar.transition("nope", "probation") is False


def test_routing_candidates_only_active(tmp_path):
    ar = _archive(tmp_path)
    root = ar.create_root("root", _spec(tags=("general",)))
    cand = ar.create_child(root.id, "cand", _spec(tags=("writing",)))
    assert [n.id for n in ar.routing_candidates()] == [root.id]
    assert [n.id for n in ar.routing_candidates("general")] == [root.id]
    assert ar.routing_candidates("writing") == []  # candidate 不参与
    ar.transition(cand.id, "probation")
    ar.transition(cand.id, "active")
    assert [n.id for n in ar.routing_candidates("writing")] == [cand.id]


# --- 恢复点 ---
def test_checkpoint_is_snapshot_and_restore_creates_new_candidate(tmp_path):
    ar = _archive(tmp_path, {"core": "0.62.7"})
    root = ar.create_root("root", _spec("a", tags=("general",)))
    child = ar.create_child(root.id, "child", _spec("b", tags=("writing",)))
    ar.transition(child.id, "probation")
    ar.transition(child.id, "active")
    ar.add_evidence(child.id, EvidenceRef("e1", "trial", "fp-1", "pass"))

    cp = ar.checkpoint(child.id)
    assert isinstance(cp, Checkpoint)
    assert cp.spec.tools == ("b",)
    assert cp.evidence_ids == ("e1",)
    assert cp.dependencies == {"core": "0.62.7"}

    restored = ar.restore(child.id)
    assert restored is not None
    assert restored.lifecycle == "candidate"     # 新节点是 candidate
    assert restored.parent_id == child.id        # 血统保留
    assert restored.spec.tools == ("b",)         # 配置恢复
    assert ar.get(child.id).lifecycle == "active"  # 原节点不变


def test_restore_retired_node_still_works(tmp_path):
    ar = _archive(tmp_path)
    root = ar.create_root("root", _spec())
    child = ar.create_child(root.id, "child", _spec("x"))
    ar.transition(child.id, "retired")
    restored = ar.restore(child.id)
    assert restored and restored.lifecycle == "candidate"
    assert ar.get(child.id).lifecycle == "retired"  # 不复活


def test_checkpoint_does_not_contain_memory(tmp_path):
    """关键契约：恢复点不含个人记忆/人格/会话历史字段。"""
    ar = _archive(tmp_path)
    root = ar.create_root("root", _spec())
    cp = ar.checkpoint(root.id)
    d = cp.to_dict()
    blob = str(d)
    for forbidden in ("memory", "persona", "history", "context", "goals"):
        assert forbidden not in blob.lower()


# --- 持久化 ---
def test_persists_across_sessions(tmp_path):
    path = tmp_path / "evolution.json"
    ar = EvolutionArchive(path)
    root = ar.create_root("root", _spec("a", tags=("general",)))
    child = ar.create_child(root.id, "child", _spec("b", tags=("writing",)))
    ar.transition(child.id, "probation")
    ar.add_evidence(child.id, EvidenceRef("e1", "regression", "fp", "pass"))

    ar2 = EvolutionArchive(path)
    assert ar2.count() == 2
    assert ar2.root.id == root.id
    assert ar2.get(child.id).lifecycle == "probation"
    assert ar2.get(child.id).evidence[0].id == "e1"
    # 版本号跨会话延续：新子节点版本 > 已有最大版本
    new_child = ar2.create_child(root.id, "new", _spec())
    assert new_child.version > child.version


def test_corrupt_file_isolated(tmp_path):
    path = tmp_path / "evolution.json"
    path.write_text("{bad json", encoding="utf-8")
    ar = EvolutionArchive(path)
    assert ar.count() == 0
    assert path.with_suffix(".json.corrupt").exists()


def test_status_counts(tmp_path):
    ar = _archive(tmp_path)
    root = ar.create_root("root", _spec())
    c1 = ar.create_child(root.id, "c1", _spec())
    c2 = ar.create_child(root.id, "c2", _spec())
    ar.transition(c1.id, "probation")
    ar.transition(c2.id, "probation")
    ar.transition(c2.id, "active")
    assert ar.status() == {"active": 2, "probation": 1}
