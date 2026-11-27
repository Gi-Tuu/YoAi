"""S5-0 回归：多个实例共享同一个文件时，不再互相覆盖、能看到彼此的写入。

复现的原始 bug：用户会话"记住我住在杭州"后，定时任务会话（构造更早、一直缓存）
再写一条事实，文件里就只剩后者。
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.context import PersonalContext  # noqa: E402
from yoai.goals import GoalManager, add_goal_listener  # noqa: E402
from yoai.temporal_memory import TemporalMemory  # noqa: E402


def test_facts_from_two_instances_are_not_lost(tmp_path):
    path = tmp_path / "context.json"
    user = PersonalContext(path)
    sched = PersonalContext(path)            # 构造得早、一直缓存的另一个会话
    user.remember("城市", "杭州")
    sched.remember("提醒", "已提醒喝水")
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert set(on_disk) == {"城市", "提醒"}
    assert user.recall("提醒") == "已提醒喝水"
    assert sched.list_all() == {"城市": "杭州", "提醒": "已提醒喝水"}


def test_forget_in_one_instance_is_seen_by_the_other(tmp_path):
    path = tmp_path / "context.json"
    a, b = PersonalContext(path), PersonalContext(path)
    a.remember("k", "v")
    assert b.recall("k") == "v"
    assert b.forget("k") is True
    assert a.recall("k") is None and a.count() == 0


def test_external_rewrite_and_delete_are_picked_up(tmp_path):
    path = tmp_path / "context.json"
    ctx = PersonalContext(path)
    ctx.remember("a", "1")
    # 另一个进程（例如命令行工具）直接改了文件
    path.write_text(json.dumps({"b": {"value": "2", "tag": "", "created_at": "", "updated_at": ""}}),
                    encoding="utf-8")
    assert ctx.list_all() == {"b": "2"}
    path.unlink()
    assert ctx.list_all() == {}


def test_goals_created_elsewhere_are_visible(tmp_path):
    path = tmp_path / "goals.json"
    user, sched = GoalManager(path), GoalManager(path)
    gid = user.create_goal("学中文")
    assert [g["title"] for g in sched.list_goals()] == ["学中文"]
    assert sched.set_status(gid, "active") is True
    assert user.get_goal(gid)["status"] == "active"
    other = sched.create_goal("推进 YoAi")
    assert {g["id"] for g in user.active_goals()} == {gid, other}


def test_temporal_events_merge_across_instances(tmp_path):
    path = tmp_path / "temporal_memory.json"
    a, b = TemporalMemory(path), TemporalMemory(path)
    a.remember_event("第一次去西湖", event_time="2026-11-20T10:00:00+08:00", tag="travel")
    b.remember_event("开始学中文", event_time="2026-11-22T16:00:00+08:00", tag="study")
    assert a.count() == 2 and b.count() == 2
    assert {e["what"] for e in a.recent_events(5)} == {"第一次去西湖", "开始学中文"}


def test_concurrent_writes_from_threads_keep_everything(tmp_path):
    path = tmp_path / "context.json"
    instances = [PersonalContext(path) for _ in range(4)]

    def work(i: int) -> None:
        for j in range(15):
            instances[i].remember(f"k{i}-{j}", j)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert PersonalContext(path).count() == 60


def test_goal_listener_receives_created_and_status_changes(tmp_path):
    events = []
    remove = add_goal_listener(lambda ev, goal, mgr, **extra: events.append((ev, goal["title"], extra)))
    try:
        mgr = GoalManager(tmp_path / "goals.json")
        gid = mgr.create_goal("写论文")
        mgr.set_status(gid, "active")
        mgr.set_status(gid, "active")          # 状态没变：不通知
        mgr.set_status(gid, "done")
        mgr.set_status("nope", "done")         # 不存在：不通知
    finally:
        remove()
    assert events == [
        ("goal_created", "写论文", {}),
        ("goal_status_changed", "写论文", {"old_status": "pending"}),
        ("goal_status_changed", "写论文", {"old_status": "active"}),
    ]
    mgr.create_goal("取消注册后")
    assert len(events) == 3


def test_broken_listener_does_not_break_goal_writes(tmp_path):
    def boom(*a, **k):
        raise RuntimeError("坏了")
    remove = add_goal_listener(boom)
    try:
        mgr = GoalManager(tmp_path / "goals.json")
        gid = mgr.create_goal("x")
        assert mgr.get_goal(gid)["title"] == "x"
    finally:
        remove()
