"""Tauri runtime 协议层测试（不依赖 PySide6 / 不联网）。

覆盖：protocol 构造器字段与前端 types/ipc.ts 的契约、bootstrap 纯函数
（clean_final_text / resolve_model_name / agent_kwargs）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TAURI = Path(__file__).resolve().parents[1] / "apps" / "desktop-tauri" / "runtime"
sys.path.insert(0, str(_TAURI))

from protocol import (  # noqa: E402
    PROTOCOL_VERSION, Seq, approval_request, archive_state, chat_msg,
    chat_state, encode, error, event, final, ready, snapshot, status,
)
from yoai.bootstrap import agent_kwargs, clean_final_text, resolve_model_name  # noqa: E402


# ---- Seq：每 run 独立单调递增 ----

def test_seq_per_run_monotonic_and_reset():
    seq = Seq()
    assert [seq.for_run("t", "r1"), seq.for_run("t", "r1")] == [0, 1]
    assert seq.for_run("t", "r2") == 0          # 不同 run 不串号
    seq.reset_run("t", "r1")
    assert seq.for_run("t", "r1") == 0          # 重置后从头计数


def test_encode_compact_ascii_false():
    line = encode({"type": "hello", "text": "中文"})
    assert line.endswith("\n") and "中文" in line
    assert ", " not in line                      # 紧凑分隔
    assert json.loads(line)["text"] == "中文"


# ---- 消息构造器：字段名与前端契约一一对应 ----

def test_snapshot_fields():
    m = snapshot(sessions=[{"id": "a", "name": "s"}], current_id="a",
                 history=[{"role": "user", "text": "hi"}], model="spark-x2.6",
                 facts={"名": "值"}, goals=[{"id": "g", "title": "t", "status": "pending"}],
                 write_stats={"events": 2}, tools=["now"])
    assert m["type"] == "snapshot"
    assert m["model"] == "spark-x2.6" and m["write_stats"]["events"] == 2
    assert m["history"][0]["role"] == "user"


def test_chat_state_and_msg_fields():
    cs = chat_state(conversations=[{"id": "g1", "name": "群", "kind": "group", "members": 2}],
                    external=[{"name": "邮箱", "level": "L2", "available": True}])
    assert cs["type"] == "chat.state"
    assert cs["conversations"][0]["kind"] == "group"
    cm = chat_msg(target="g1", sender="ext-邮箱", name="邮箱", content="你好", own=False)
    assert cm["type"] == "chat.msg" and cm["own"] is False
    assert {"target", "sender", "name", "content", "own"} <= set(cm)


def test_archive_state_fields():
    n = {"id": "root", "name": "通用根", "lifecycle": "active", "version": 1,
         "parent_id": "", "depth": 0, "capability_tags": [], "tools": [],
         "strategy_bias": "", "model_tier": "", "diff": "", "evidence_count": 0,
         "created_at": "", "prompt_suffix": ""}
    ar = archive_state(nodes=[n])
    assert ar["type"] == "archive.state" and ar["nodes"][0]["depth"] == 0


def test_v1_messages_unchanged():
    assert ready(tools=[], sessions=[], config={}, python="3")["protocol"] == PROTOCOL_VERSION
    s = status("t", "r", 0, "running", "")
    assert s["state"] == "running" and s["seq"] == 0
    e = event("t", "r", 1, "tool_call", {"tool": "now"})
    assert e["event"] == "tool_call"
    f = final("t", "r", 2, "答案")
    assert f["text"] == "答案"
    a = approval_request("t", "r", 3, "file_create", "确认执行该操作？", "{}")
    assert a["tool"] == "file_create"
    assert error("runtime", "boom")["stage"] == "runtime"


# ---- bootstrap 纯函数 ----

def test_clean_final_text_unwraps_tool_output():
    raw = "<tool_output><attribution>查询</attribution>结果数据</tool_output>\n\n结论"
    out = clean_final_text(raw)
    assert "结果数据" in out and "<tool_output" not in out and "<attribution>" not in out


def test_clean_final_text_collapses_blank_lines():
    assert clean_final_text("a\n\n\n\n\nb") == "a\n\nb"


def test_resolve_model_name_walks_wrappers():
    class Adapter:
        name = "算里 DeepSeek"

        def _config(self):
            return ("base", "key", "spark-x2.6")

    class Gateway:
        adapter = Adapter()

    class Expert:
        base = Gateway()

    assert resolve_model_name(Expert()) == "spark-x2.6"

    class DemoModel:
        pass

    assert resolve_model_name(DemoModel()) == "离线 Demo"


def test_agent_kwargs_builtin_tools_off(monkeypatch):
    monkeypatch.setenv("YOAI_BUILTIN_TOOLS", "0")
    kwargs = agent_kwargs(auto_approve=True)
    assert kwargs["builtin_tools"] is False and "policy" in kwargs


def test_clean_final_text_removes_legacy_dsml_blocks():
    """历史遗留 DSML（11-24 路由根治前）不显示乱码；正常提到 DSML 一词保留。"""
    raw = (
        "正常说明文字\n\n"
        "<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name=\"list_facts\"> "
        "<｜｜DSML｜｜ parameter name=\"reason\" string=\"true\">检查\n"
        "</｜｜DSML｜｜ parameter> </｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>"
    )
    out = clean_final_text(raw)
    assert "正常说明文字" in out
    assert "DSML" not in out and "list_facts" not in out and "invoke" not in out

    # 模型在正文里正常讨论 DSML 时不能误删
    prose = "DSML 块被解析、被发出去了，但没有结果块回来。"
    assert clean_final_text(prose) == prose


def test_thinking_store_append_load_and_trim(tmp_path):
    """thinking 持久化：按会话隔离、可读回、上限裁剪。"""
    from yoai.thinking_store import MAX_RECORDS, ThinkingStore

    store = ThinkingStore(tmp_path)
    store.append(session_id="s1", run_id="r1", text="思考一", user_input="问题一")
    store.append(session_id="s1", run_id="r2", text="思考二", user_input="问题二")
    store.append(session_id="s2", run_id="r3", text="别的会话", user_input="问题三")

    s1 = store.load("s1")
    assert len(s1) == 2 and s1[0]["text"] == "思考一" and s1[1]["input"] == "问题二"
    assert len(store.load("s2")) == 1
    assert store.load("missing") == []

    # 上限裁剪保留最近记录
    for i in range(MAX_RECORDS + 5):
        store.append(session_id="s1", run_id=f"r{i}", text=f"t{i}")
    assert len(store.load("s1")) == MAX_RECORDS
    assert store.load("s1")[-1]["text"] == f"t{MAX_RECORDS + 4}"


def test_thinking_store_append_load_and_trim(tmp_path):
    """thinking 持久化：按会话隔离、可读回、上限裁剪。"""
    from yoai.thinking_store import MAX_RECORDS, ThinkingStore

    store = ThinkingStore(tmp_path)
    store.append(session_id="s1", run_id="r1", text="思考一", user_input="问题一")
    store.append(session_id="s1", run_id="r2", text="思考二", user_input="问题二")
    store.append(session_id="s2", run_id="r3", text="别的会话", user_input="问题三")

    s1 = store.load("s1")
    assert len(s1) == 2 and s1[0]["text"] == "思考一" and s1[1]["input"] == "问题二"
    assert len(store.load("s2")) == 1
    assert store.load("missing") == []

    # 上限裁剪保留最近记录
    for i in range(MAX_RECORDS + 5):
        store.append(session_id="s1", run_id=f"r{i}", text=f"t{i}")
    assert len(store.load("s1")) == MAX_RECORDS
    assert store.load("s1")[-1]["text"] == f"t{MAX_RECORDS + 4}"
