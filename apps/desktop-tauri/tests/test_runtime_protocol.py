"""Desktop IPC runtime 离线测试：协议层 + runtime 命令分发（mock agent，不联网）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(RUNTIME))

from protocol import Seq, encode, error, event, final, ready, status  # noqa: E402


def test_protocol_messages_are_json_lines():
    for msg in (
        ready(tools=["a"], sessions=[], config={}, python="3.13"),
        status("t", "r", 0, "running"),
        event("t", "r", 1, "tool_call", {"tool": "x"}),
        final("t", "r", 2, "done"),
        error("runtime", "boom"),
    ):
        line = encode(msg)
        assert line.endswith("\n")
        parsed = json.loads(line)
        assert parsed["v"] == 1
        assert "\n" not in line[:-1]   # 单行


def test_seq_per_run_independent():
    seq = Seq()
    assert [seq.for_run("t1", "r1") for _ in range(3)] == [0, 1, 2]
    assert [seq.for_run("t1", "r2") for _ in range(2)] == [0, 1]
    seq.reset_run("t1", "r1")
    assert seq.for_run("t1", "r1") == 0


@pytest.mark.asyncio
async def test_runtime_task_start_emits_ordered_events(monkeypatch, capsys):
    """runtime 把 astream 事件翻成有序协议消息（mock agent，零内核改动）。"""
    import yoai_runtime as yr

    rt = yr.Runtime()

    class FakeAgent:
        async def astream(self, task):
            yield SimpleNamespace(type=SimpleNamespace(value="strategy_selected"),
                                  data={"strategy": "react"})
            yield SimpleNamespace(type=SimpleNamespace(value="done"),
                                  data={"final_text": "ok"})

    rt.agent = FakeAgent()
    rt._ensure_agent = lambda: None   # 不构造真 agent
    await rt.start_task("t1", "r1", "任务")
    # 等任务协程完成
    import asyncio
    for _ in range(50):
        if not rt.tasks:
            break
        await asyncio.sleep(0.01)

    lines = [json.loads(l) for l in capsys.readouterr().out.strip().split("\n") if l]
    types = [(m["type"], m.get("event") or m.get("state")) for m in lines]
    assert ("status", "running") in types
    assert ("event", "strategy_selected") in types
    assert ("final", None) in types
    assert ("status", "done") in types
    seqs = [m["seq"] for m in lines if m.get("run_id") == "r1"]
    assert seqs == sorted(set(seqs))   # 严格递增无重复


@pytest.mark.asyncio
async def test_runtime_unknown_command_reports_error(capsys):
    import yoai_runtime as yr
    rt = yr.Runtime()
    await rt.handle({"type": "no_such_cmd"})
    out = capsys.readouterr().out.strip()
    msg = json.loads(out)
    assert msg["type"] == "error" and "no_such_cmd" in msg["message"]


@pytest.mark.asyncio
async def test_runtime_cancel_emits_cancelled(monkeypatch, capsys):
    """取消任务必须发 status(cancelled)，不能静默。"""
    import asyncio
    import yoai_runtime as yr
    rt = yr.Runtime()

    class SlowAgent:
        async def astream(self, task):
            yield SimpleNamespace(type=SimpleNamespace(value="strategy_selected"), data={})
            await asyncio.sleep(5)
            yield SimpleNamespace(type=SimpleNamespace(value="done"), data={"final_text": "never"})

    rt.agent = SlowAgent()
    rt._ensure_agent = lambda: None
    await rt.start_task("tc", "rc", "慢任务")
    await asyncio.sleep(0.05)
    rt.cancel_task("tc", "rc")
    if "rc" in rt.tasks:
        await rt.tasks["rc"]
    lines = [json.loads(l) for l in capsys.readouterr().out.strip().split("\n") if l]
    states = [m.get("state") for m in lines if m["type"] == "status"]
    assert "cancelled" in states
