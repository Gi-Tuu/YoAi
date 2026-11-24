"""thinking 事件链路测试（2026-11-24）。

Core 把 thinking 块存进 raw_content_blocks / 历史，但**不发事件**——UI 拿不到。
YoAi 侧在 CoreAnthropicModelProvider 拦截 → YoAiAgent.astream drain 成自定义事件。
不改 Core 源码，跟随上游更新。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.agent import YoAiAgent, YoAiEvent  # noqa: E402
from yoai.models.core_anthropic_provider import CoreAnthropicModelProvider  # noqa: E402
from yoai.demo_model import DemoModel  # noqa: E402


def test_capture_thinking_from_raw_blocks():
    provider = CoreAnthropicModelProvider.__new__(CoreAnthropicModelProvider)
    provider.thinking_outbox = []
    response = SimpleNamespace(
        raw_content_blocks=[
            {"type": "thinking", "thinking": "先查偏好键"},
            {"type": "signature", "signature": "abc"},   # 无文本，不展示
            {"type": "thinking", "thinking": "   "},     # 空文本忽略
            {"type": "redacted_thinking", "text": "隐藏推理"},
            "not a dict",
        ],
    )
    provider._capture_thinking(response)
    assert provider.thinking_outbox == ["先查偏好键", "隐藏推理"]


def test_drain_thinking_clears_outbox():
    provider = CoreAnthropicModelProvider.__new__(CoreAnthropicModelProvider)
    provider.thinking_outbox = ["a", "b"]
    assert provider.drain_thinking() == ["a", "b"]
    assert provider.drain_thinking() == []


@pytest.mark.asyncio
async def test_astream_emits_thinking_events(tmp_path, monkeypatch):
    """astream 先发 thinking 事件，再发对应 core 事件；DONE 后补 drain 兜底。"""
    from yai_core import EventType, AgentEvent

    pending = ["用户在问偏好"]
    def _drain():
        nonlocal pending
        items, pending = pending, []
        return items
    provider = SimpleNamespace(drain_thinking=_drain)
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path, temporal_memory=False)
    agent.core.model = provider

    async def fake_astream(task):
        yield AgentEvent(EventType.TOOL_CALL, {"tool": "list_facts"})
        yield AgentEvent(EventType.DONE, {"final_text": "深色主题"})

    monkeypatch.setattr(agent.core, "astream", fake_astream)
    events = [e async for e in agent.astream("偏好？")]
    kinds = [(getattr(e.type, "value", ""), e.data) for e in events]
    assert kinds[0][0] == "thinking" and kinds[0][1]["text"] == "用户在问偏好"
    assert kinds[1][0] == "tool_call"
    assert kinds[2][0] == "done"


@pytest.mark.asyncio
async def test_astream_without_thinking_provider_is_unaffected(tmp_path, monkeypatch):
    """未接 thinking 的模型（DemoModel 等）行为完全不变。"""
    from yai_core import EventType, AgentEvent

    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path, temporal_memory=False)

    async def only_done(task):
        yield AgentEvent(EventType.DONE, {"final_text": "ok"})

    monkeypatch.setattr(agent.core, "astream", only_done)
    events = [e async for e in agent.astream("x")]
    assert len(events) == 1 and events[0].data["final_text"] == "ok"
