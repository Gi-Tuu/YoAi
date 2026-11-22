"""Personal Context 与 Goal Manager 的持久化单测（离线、标准库）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yoai.context import PersonalContext  # noqa: E402
from yoai.goals import GoalManager  # noqa: E402


def test_context_remember_recall(tmp_path):
    ctx = PersonalContext(tmp_path / "context.json")
    assert ctx.remember("theme", "dark", tag="ui") == "已记住：theme"
    assert ctx.recall("theme") == "dark"
    assert ctx.count() == 1


def test_context_persists_across_instances(tmp_path):
    path = tmp_path / "context.json"
    PersonalContext(path).remember("city", "上海")
    # 新实例模拟跨会话恢复
    assert PersonalContext(path).recall("city") == "上海"


def test_context_forget(tmp_path):
    ctx = PersonalContext(tmp_path / "context.json")
    ctx.remember("tmp", "x")
    assert ctx.forget("tmp") is True
    assert ctx.forget("tmp") is False
    assert ctx.recall("tmp") is None


def test_context_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "context.json"
    path.write_text("{bad json", encoding="utf-8")
    ctx = PersonalContext(path)
    assert ctx.count() == 0
    assert path.with_suffix(".json.corrupt").exists()


def test_goal_create_and_status(tmp_path):
    goals = GoalManager(tmp_path / "goals.json")
    gid = goals.create_goal("完成 Phase 0", ["审计 Core", "搭骨架"])
    assert goals.get_goal(gid)["status"] == "pending"
    assert goals.set_status(gid, "active") is True
    assert goals.set_status(gid, "done") is True
    assert goals.get_goal(gid)["steps"] == ["审计 Core", "搭骨架"]
    assert goals.list_goals("done")[0]["id"] == gid


def test_goal_invalid_status_rejected(tmp_path):
    goals = GoalManager(tmp_path / "goals.json")
    gid = goals.create_goal("t")
    assert goals.set_status(gid, "bogus") is False
    assert goals.set_status("missing", "done") is False


def test_goal_persists_across_instances(tmp_path):
    path = tmp_path / "goals.json"
    GoalManager(path).create_goal("跨会话目标")
    reloaded = GoalManager(path)
    assert reloaded.count() == 1
    assert reloaded.list_goals()[0]["title"] == "跨会话目标"
