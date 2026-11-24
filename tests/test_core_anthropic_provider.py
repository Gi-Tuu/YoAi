"""CoreAnthropicModelProvider 测试 — Core 官方 Provider 的 YoAi 生产包装。

覆盖四件生产契约（全部离线，假 client 注入）：
1. 环境变量判据与旧 adapter 一致（ANTHROPIC_BASE_URL/AUTH_TOKEN/MODEL）；
2. 异常转友好错误：SDK 异常不外抛，转成 "[模型网关错误]..." 文本；
3. stall 过渡语重试：只说"我去查一下"且给了工具时追加一次明确指令；
4. usage 真实累计（不臆造）。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from yoai.models.core_anthropic_provider import (
    CoreAnthropicModelProvider,
    core_anthropic_available,
)

_TOOLS = [{
    "type": "function",
    "function": {"name": "lookup", "description": "查",
                 "parameters": {"type": "object", "properties": {}}},
}]


def _resp(text: str, *, tool_use: dict | None = None, usage=(10, 5)):
    blocks: list = []
    if tool_use:
        blocks.append({"type": "tool_use", **tool_use})
    if text:
        blocks.append({"type": "text", "text": text})
    return SimpleNamespace(
        content=blocks,
        usage={"input_tokens": usage[0], "output_tokens": usage[1]},
    )


def _events_from_response(resp):
    """把一次性假响应转成 SDK 流式事件序列（供 stream 路径测试复用）。"""
    events = []
    usage = getattr(resp, "usage", None) or {}
    get = (lambda k: getattr(usage, k, 0)) if not isinstance(usage, dict) else (
        lambda k: usage.get(k, 0))
    for idx, block in enumerate(getattr(resp, "content", None) or []):
        b = block if isinstance(block, dict) else vars(block)
        kind = b.get("type", "text")
        start = {"type": kind}
        if kind == "tool_use":
            start.update({k: v for k, v in b.items() if k in ("id", "name")})
        # text/thinking 的文本由 delta 累积，start 不带，避免重复
        events.append(SimpleNamespace(type="content_block_start", index=idx,
                                      content_block=SimpleNamespace(**start)))
        if kind == "text":
            events.append(SimpleNamespace(
                type="content_block_delta", index=idx,
                delta=SimpleNamespace(type="text_delta", text=b.get("text", ""))))
        elif kind == "tool_use":
            import json
            events.append(SimpleNamespace(
                type="content_block_delta", index=idx,
                delta=SimpleNamespace(type="input_json_delta",
                                      partial_json=json.dumps(b.get("input", {})))))
        events.append(SimpleNamespace(type="content_block_stop", index=idx))
    events.append(SimpleNamespace(
        type="message_delta",
        usage=SimpleNamespace(input_tokens=get("input_tokens"),
                              output_tokens=get("output_tokens"))))
    return events


class _FakeStream:
    def __init__(self, events):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        async def _gen():
            for e in self._events:
                yield e
        return _gen()


class _FakeMessages:
    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeStream(_events_from_response(item))


class _FakeClient:
    def __init__(self, script):
        self.messages = _FakeMessages(script)


@pytest.fixture
def anthropic_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example/anthropic")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    monkeypatch.delenv("YOAI_ANTHROPIC_PROMPT_CACHE", raising=False)
    monkeypatch.delenv("ANTHROPIC_MAX_TOKENS", raising=False)


def _make(monkeypatch, script, anthropic_env):
    provider = CoreAnthropicModelProvider()
    provider._inner.client = _FakeClient(script)
    return provider


def test_available_requires_all_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert not core_anthropic_available()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "k")
    monkeypatch.setenv("ANTHROPIC_MODEL", "m")
    assert core_anthropic_available()
    # ANTHROPIC_API_KEY 也可作为凭据来源
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k2")
    assert core_anthropic_available()


def test_unavailable_env_cannot_construct(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    # base_url 缺失时 SDK 客户端仍可构造（走官方默认），但生产接线以
    # core_anthropic_available() 为准；这里只验证 available 门禁在接线侧生效。
    assert not core_anthropic_available()


def test_plain_chat_passthrough_and_usage(anthropic_env):
    provider = _make(None, [_resp("你好呀")], anthropic_env)
    resp = _run(provider.achat([{"role": "user", "content": "hi"}]))
    assert resp.content == "你好呀"
    assert not resp.tool_calls
    assert provider.total_usage == {"prompt_tokens": 10, "completion_tokens": 5,
                                    "total_tokens": 15}
    assert provider.last_status == "ok"


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_exception_becomes_friendly_text(anthropic_env):
    provider = _make(None, [RuntimeError("连接被重置")], anthropic_env)
    resp = _run(provider.achat([{"role": "user", "content": "hi"}]))
    # 不外抛，转成可读错误文本（Core loop 对 achat 异常是 raise 不吞）
    assert "[模型网关错误]" in resp.content
    assert "连接被重置" in resp.content
    assert provider.last_status.startswith("error:")


def test_tool_call_passthrough(anthropic_env):
    tool_use = {"id": "t1", "name": "lookup", "input": {"q": "x"}}
    provider = _make(None, [_resp("", tool_use=tool_use)], anthropic_env)
    resp = _run(provider.achat([{"role": "user", "content": "hi"}], tools=_TOOLS))
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "lookup"
    assert resp.tool_calls[0].id == "t1"


def test_stall_retry_uses_nudge(anthropic_env):
    tool_use = {"id": "t2", "name": "lookup", "input": {}}
    provider = _make(None, [_resp("我去查一下"), _resp("结果是 42", tool_use=tool_use)],
                     anthropic_env)
    resp = _run(provider.achat([{"role": "user", "content": "帮我查"}], tools=_TOOLS))
    # 第二次响应被采纳：带 tool_calls 不算 stall
    assert resp.content == "结果是 42"
    assert len(resp.tool_calls) == 1
    fake = provider._inner.client
    assert len(fake.messages.calls) == 2
    # 重试消息里应包含 assistant 过渡语 + nudge 指令
    retried_messages = fake.messages.calls[1]["messages"]
    assert retried_messages[-1]["role"] == "user"
    assert "直接调用工具" in retried_messages[-1]["content"][0]["text"]


def test_stall_persists_returns_original(anthropic_env):
    provider = _make(None, [_resp("我马上看"), _resp("好的，我去查查")], anthropic_env)
    resp = _run(provider.achat([{"role": "user", "content": "帮我查"}], tools=_TOOLS))
    # 重试仍是过渡语 → 返回原响应，不无限纠缠
    assert resp.content == "我马上看"
    assert not resp.tool_calls


def test_stall_retry_non_stall_answer_adopted(anthropic_env):
    # 重试给出了非过渡语回答 → 采纳重试结果（正则不误伤"好的，这就查"这类
    # 完整回答，与 GatewayModelProvider 原行为一致）
    provider = _make(None, [_resp("我马上看"), _resp("好的，这就查：结果是 42")],
                     anthropic_env)
    resp = _run(provider.achat([{"role": "user", "content": "帮我查"}], tools=_TOOLS))
    assert resp.content == "好的，这就查：结果是 42"


def test_no_tools_no_retry(anthropic_env):
    provider = _make(None, [_resp("我去查一下")], anthropic_env)
    resp = _run(provider.achat([{"role": "user", "content": "hi"}]))
    # 没给 tools → 无重试意义，原样返回
    assert resp.content == "我去查一下"
    assert len(provider._inner.client.messages.calls) == 1


def test_tools_converted_to_anthropic_shape(anthropic_env):
    provider = _make(None, [_resp("ok")], anthropic_env)
    _run(provider.achat([{"role": "user", "content": "hi"}], tools=_TOOLS))
    sent_tools = provider._inner.client.messages.calls[0]["tools"]
    assert sent_tools[0]["name"] == "lookup"
    assert "input_schema" in sent_tools[0]
    assert "function" not in sent_tools[0]


def test_prompt_cache_default_off(anthropic_env):
    provider = _make(None, [_resp("ok")], anthropic_env)
    _run(provider.achat([{"role": "user", "content": "hi"}]))
    kwargs = provider._inner.client.messages.calls[0]
    # 默认不开 cache_control（DeepSeek 网关兼容性未实测）
    assert isinstance(kwargs.get("system"), str) or kwargs.get("system") is None
    assert "cache_control" not in str(kwargs.get("tools", ""))


def test_prompt_cache_env_on(anthropic_env, monkeypatch):
    monkeypatch.setenv("YOAI_ANTHROPIC_PROMPT_CACHE", "1")
    provider = CoreAnthropicModelProvider()
    provider._inner.client = _FakeClient([_resp("ok")])
    system_text = [{"role": "system", "content": "你是助手"}]
    _run(provider.achat(system_text))
    system = provider._inner.client.messages.calls[0]["system"]
    assert isinstance(system, list) and system[0]["cache_control"] == {"type": "ephemeral"}
