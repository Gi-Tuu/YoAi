"""GatewayModelProvider 测试：消息渲染、usage 透传、错误不抛、工具调用留空。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.types import ModelResponse, ToolCallRequest  # noqa: E402

from yoai.adapters.base import AdapterResult, PeerAdapter  # noqa: E402
from yoai.models import GatewayModelProvider  # noqa: E402


class FakeAdapter(PeerAdapter):
    level = "L2"

    def __init__(self, result: AdapterResult) -> None:
        super().__init__("fake")
        self.result = result
        self.seen = ""

    def available(self) -> bool:
        return True

    def send(self, message: str) -> AdapterResult:
        self.seen = message
        return self.result


def test_achat_returns_text_and_usage():
    adapter = FakeAdapter(AdapterResult(
        True, text="真实回答", level="L2",
        meta={"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
    ))
    provider = GatewayModelProvider(adapter)
    msgs = [
        {"role": "system", "content": "你是 YoAi"},
        {"role": "user", "content": "你好"},
    ]
    resp: ModelResponse = asyncio.run(provider.achat(msgs))
    assert resp.content == "真实回答"
    assert resp.usage is not None and resp.usage.total_tokens == 15
    assert resp.tool_calls == []
    assert provider.calls == 1
    assert "[系统] 你是 YoAi" in adapter.seen
    assert "[用户] 你好" in adapter.seen


def test_gateway_error_does_not_raise():
    adapter = FakeAdapter(AdapterResult(False, level="L2", detail="429 额度用尽"))
    provider = GatewayModelProvider(adapter)
    resp = asyncio.run(provider.achat([{"role": "user", "content": "hi"}]))
    assert "模型网关错误" in resp.content and "429" in resp.content
    assert resp.usage is None


def test_no_usage_when_missing():
    adapter = FakeAdapter(AdapterResult(True, text="ok", level="L2"))
    provider = GatewayModelProvider(adapter)
    resp = asyncio.run(provider.achat([{"role": "user", "content": "hi"}]))
    assert resp.usage is None


def test_multimodal_content_list_degraded():
    adapter = FakeAdapter(AdapterResult(True, text="ok", level="L2"))
    provider = GatewayModelProvider(adapter)
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "看这张图"},
        {"type": "image_url", "image_url": {"url": "x"}},
    ]}]
    asyncio.run(provider.achat(msgs))
    assert "看这张图" in adapter.seen


def test_include_system_false():
    adapter = FakeAdapter(AdapterResult(True, text="ok", level="L2"))
    provider = GatewayModelProvider(adapter, include_system=False)
    asyncio.run(provider.achat([
        {"role": "system", "content": "隐藏"},
        {"role": "user", "content": "显示"},
    ]))
    assert "隐藏" not in adapter.seen and "显示" in adapter.seen


def test_describe_is_honest():
    adapter = FakeAdapter(AdapterResult(True, text="ok", level="L2"))
    d = GatewayModelProvider(adapter).describe()
    assert d["mode"] == "text_only" and d["tool_calls"] is False


def test_stream_tool_calls_flattened_for_gateway():
    """流式 SSE 聚合的嵌套 tool_calls 必须扁平化，否则网关层静默丢弃。"""
    from yoai.models.suanli_adapter import flatten_stream_tool_calls

    raw = {
        0: {"id": "call_1", "type": "function",
            "function": {"name": "remember_fact",
                         "arguments": '{"key":"偏好","value":"深色"}'}},
        1: {"id": "call_2", "type": "function",
            "function": {"name": "recall_fact", "arguments": '{"key":"偏好"}'}},
    }
    calls = flatten_stream_tool_calls(raw)
    assert len(calls) == 2
    assert calls[0] == {"id": "call_1", "name": "remember_fact",
                        "arguments": {"key": "偏好", "value": "深色"}}
    assert calls[1]["name"] == "recall_fact"

    # GatewayModelProvider 能正确转成 ToolCallRequest
    adapter = FakeAdapter(AdapterResult(True, text="", level="L2", tool_calls=calls))
    resp = asyncio.run(GatewayModelProvider(adapter).achat([{"role": "user", "content": "x"}]))
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].name == "remember_fact"
    assert resp.tool_calls[0].arguments["key"] == "偏好"
    assert resp.tool_calls[1].name == "recall_fact"
