"""过渡语 re-ask 测试：模型只说'我去查'时不该被当最终答案。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.adapters.base import AdapterResult
from yoai.models.gateway_provider import GatewayModelProvider
from yoai.models.suanli_adapter import SuanliAdapter


class _FakeAdapter:
    def __init__(self, script):
        self.script = script
        self.n = 0
        self.seen = []

    def capabilities(self):
        return {"tool_calls"}

    def send(self, message, *, tools=None, messages=None):
        self.n += 1
        last = ""
        if messages:
            last = str(messages[-1].get("content") or "")
        self.seen.append(last)
        resp = self.script[min(self.n - 1, len(self.script) - 1)]
        return AdapterResult(True, text=resp[0], tool_calls=resp[1])


def test_stall_patterns():
    # 正则已提取到共享模块 yoai.models.stall（GatewayModelProvider 与
    # CoreAnthropicModelProvider 共用同一检测），行为不变。
    from yoai.models.stall import STALL_RE
    yes = ["好的，我去查一下。", "我去查一下", "让我看看", "稍等",
           "我来试试看", "嗯，我先看看"]
    no = ["查完了：目前记住0条。", "抱歉无法访问", "已经记住了，你叫小明", "你好"]
    assert all(STALL_RE.match(s) for s in yes)
    assert all(not STALL_RE.match(s) for s in no)


def test_stall_triggers_reask_then_tool():
    adapter = _FakeAdapter([
        ("好的，我去查一下。", []),                       # 第1轮：过渡语
        ("", [{"id": "x", "name": "list_facts", "arguments": {}}]),  # re-ask后：调工具
        ("查完了。", []),
    ])
    provider = GatewayModelProvider(adapter)
    r = asyncio.run(provider.achat(
        [{"role": "user", "content": "查一下我记住了什么"}], tools=[{"type": "function"}]
    ))
    assert adapter.n == 2, adapter.n
    assert len(r.tool_calls) == 1
    assert "请直接调用工具执行" in adapter.seen[1]


def test_normal_answer_no_reask():
    adapter = _FakeAdapter([("已经记住了，你叫小明", [])])
    provider = GatewayModelProvider(adapter)
    r = asyncio.run(provider.achat(
        [{"role": "user", "content": "我叫小明，记住"}], tools=[{"type": "function"}]
    ))
    assert adapter.n == 1   # 正常回答不多请求
    assert not r.tool_calls


def test_reask_disabled():
    adapter = _FakeAdapter([("好的，我去查一下。", [])])
    provider = GatewayModelProvider(adapter, reask_on_stall=False)
    r = asyncio.run(provider.achat(
        [{"role": "user", "content": "查一下"}], tools=[{"type": "function"}]
    ))
    assert adapter.n == 1
    assert "我去查" in r.content


def test_reask_only_once_no_loop():
    """重试后仍是过渡语 → 返回原响应，不无限循环。"""
    adapter = _FakeAdapter([
        ("好的，我去查一下。", []),
        ("让我看看。", []),   # re-ask仍过渡语
    ])
    provider = GatewayModelProvider(adapter)
    r = asyncio.run(provider.achat(
        [{"role": "user", "content": "查一下"}], tools=[{"type": "function"}]
    ))
    assert adapter.n == 2   # 最多2次
    assert "我去查" in r.content   # 返回原响应
