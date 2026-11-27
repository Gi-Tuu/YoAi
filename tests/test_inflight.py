"""S5-2：被打断的对话轮次记录。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.inflight import MAX_INPUT_CHARS, MAX_KEEP, InflightTurns  # noqa: E402


def _start(t: InflightTurns, run_id: str, text: str = "帮我总结一下") -> None:
    t.start(run_id, task_id="t-" + run_id, session_id="s1", session_name="新会话", user_input=text)


def test_finished_turns_leave_nothing(tmp_path):
    t = InflightTurns(tmp_path)
    _start(t, "r1")
    t.finish("r1")
    assert InflightTurns(tmp_path).interrupted() == []


def test_unfinished_turn_becomes_interrupted_on_next_start(tmp_path):
    t = InflightTurns(tmp_path)
    _start(t, "r1", "写一份周报")
    # 进程在这里被关掉：没有 finish
    again = InflightTurns(tmp_path)
    items = again.interrupted()
    assert [i["run_id"] for i in items] == ["r1"]
    assert items[0]["input"] == "写一份周报" and items[0]["session_name"] == "新会话"
    assert items[0]["interrupted_at"] and items[0]["truncated"] is False
    # 再启动一次也还在（直到用户忽略或重发）
    assert [i["run_id"] for i in InflightTurns(tmp_path).interrupted()] == ["r1"]


def test_dismiss_removes_and_is_persistent(tmp_path):
    _start(InflightTurns(tmp_path), "r1")
    t = InflightTurns(tmp_path)
    assert t.dismiss("r1") is True and t.dismiss("r1") is False
    assert InflightTurns(tmp_path).interrupted() == []


def test_long_input_is_truncated_and_flagged(tmp_path):
    _start(InflightTurns(tmp_path), "r1", "长" * (MAX_INPUT_CHARS + 10))
    item = InflightTurns(tmp_path).interrupted()[0]
    assert item["truncated"] is True and len(item["input"]) == MAX_INPUT_CHARS


def test_keeps_only_recent_and_drops_old(tmp_path):
    path = tmp_path / "runs" / "inflight.json"
    path.parent.mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    running = {f"r{i}": {"run_id": f"r{i}", "started_at": f"2026-11-27T10:0{i}:00+00:00"} for i in range(8)}
    path.write_text(json.dumps({"running": running, "interrupted": {
        "ancient": {"run_id": "ancient", "started_at": old, "interrupted_at": old}}}), encoding="utf-8")
    items = InflightTurns(tmp_path).interrupted()
    assert len(items) == MAX_KEEP
    assert [i["run_id"] for i in items] == ["r7", "r6", "r5", "r4", "r3"]


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "runs" / "inflight.json"
    path.parent.mkdir(parents=True)
    path.write_text("{坏的", encoding="utf-8")
    assert InflightTurns(tmp_path).interrupted() == []
