"""Anthropic 消息转换测试：多个 tool_result 必须合并在紧跟的一条 user 消息。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.models.deepseek_adapter import _openai_messages_to_anthropic as conv


def _assistant_two_calls():
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call_A", "function": {"name": "list_facts", "arguments": "{}"}},
        {"id": "call_B", "function": {"name": "list_goals", "arguments": "{}"}},
    ]}


def test_multiple_tool_results_merged_into_one_user_message():
    """核心 bug 回归：Anthropic 要求同一批 tool_use 的 result 在同一条 user。"""
    out = conv([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "查一下"},
        _assistant_two_calls(),
        {"role": "tool", "content": "结果A", "tool_call_id": "call_A"},
        {"role": "tool", "content": "结果B", "tool_call_id": "call_B"},
    ])
    assert out[1]["role"] == "assistant"
    assert [b["type"] for b in out[1]["content"]] == ["tool_use", "tool_use"]
    assert out[2]["role"] == "user"
    assert [b["type"] for b in out[2]["content"]] == ["tool_result", "tool_result"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["call_A", "call_B"]


def test_tool_results_followed_by_user_message():
    out = conv([
        _assistant_two_calls(),
        {"role": "tool", "content": "A", "tool_call_id": "call_A"},
        {"role": "tool", "content": "B", "tool_call_id": "call_B"},
        {"role": "user", "content": "追问"},
    ])
    assert out[2]["content"] == "追问"   # result 刷出后 user 正常跟上


def test_single_tool_result_still_works():
    out = conv([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "X", "function": {"name": "a", "arguments": "{}"}}]},
        {"role": "tool", "content": "r", "tool_call_id": "X"},
    ])
    assert len(out) == 2
    assert out[1]["content"][0]["tool_use_id"] == "X"


def test_trailing_tool_results_flushed():
    out = conv([{"role": "tool", "content": "r", "tool_call_id": "X"}])
    assert len(out) == 1
    assert out[0]["content"][0]["type"] == "tool_result"
