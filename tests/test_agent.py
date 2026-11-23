"""端到端测试：YoAi 作为宿主驱动 Core，工具被内省、事件流完整、状态落盘。

全部离线（ScriptedModel），不依赖网络或 API Key。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core import (  # noqa: E402
    EventType,
    ModelResponse,
    ScriptedModel,
    ToolCallRequest,
)

from yoai.agent import YoAiAgent  # noqa: E402


def test_tools_are_introspected(tmp_path):
    agent = YoAiAgent(data_dir=tmp_path)
    tools = set(agent.list_tools())
    assert {
        "remember_fact",
        "recall_fact",
        "list_facts",
        "create_goal",
        "complete_goal",
        "list_goals",
    }.issubset(tools)


def test_end_to_end_task_with_tool_call(tmp_path):
    """脚本模型：先调 remember_fact 工具，再给最终答案。"""
    model = ScriptedModel(
        [
            ModelResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="c1",
                        name="remember_fact",
                        arguments={"key": "theme", "value": "dark", "tag": "ui"},
                    )
                ],
            ),
            ModelResponse(content="已记住你的主题偏好。"),
        ]
    )
    agent = YoAiAgent(model=model, data_dir=tmp_path)

    async def run():
        events = []
        async for event in agent.astream("记住我偏好深色主题"):
            events.append(event.type)
        return events

    events = asyncio.run(run())
    assert EventType.TOOL_CALL in events
    assert EventType.DONE in events
    # 工具副作用落到个人上下文
    assert agent.context.recall("theme") == "dark"
    # 跨会话恢复仍可读
    assert YoAiAgent(data_dir=tmp_path).context.recall("theme") == "dark"


def test_default_model_works_without_config(tmp_path):
    """未注入模型时占位模型可跑通，不抛异常、不伪造具体答案。"""
    agent = YoAiAgent(data_dir=tmp_path)

    async def run():
        final = None
        async for event in agent.astream("你好"):
            if event.type == EventType.DONE:
                final = event.data["final_text"]
        return final

    assert "尚未配置模型" in asyncio.run(run())


if __name__ == "__main__":
    pytest.main([__file__])


def test_memory_fallback_optin(tmp_path):
    """阶段B：memory_fallback=True 且模型0写入时，确定性兜底补上；默认关则不补。"""
    # 默认关：模型记0条也不兜底
    a = YoAiAgent(model=ScriptedModel([ModelResponse(content="ok")]),
                  data_dir=tmp_path / "off")
    async def run_off():
        async for _ in a.astream("I have 3 sisters and I live in Beijing"):
            pass
    asyncio.run(run_off())
    assert a.last_write_stats()["events"] == 0
    assert a.temporal_memory.count() == 0

    # 开启：同一句话触发兜底
    b = YoAiAgent(model=ScriptedModel([ModelResponse(content="ok")]),
                  data_dir=tmp_path / "on", memory_fallback=True)
    async def run_on():
        async for _ in b.astream("I have 3 sisters and I live in Beijing"):
            pass
    asyncio.run(run_on())
    stats = b.last_write_stats()
    assert stats["fallback"] >= 1, stats
    assert b.temporal_memory.count() >= 1

    # 寒暄不兜底（无事实信号）
    c = YoAiAgent(model=ScriptedModel([ModelResponse(content="hi")]),
                  data_dir=tmp_path / "hi", memory_fallback=True)
    async def run_hi():
        async for _ in c.astream("你好呀，今天天气怎么样"):
            pass
    asyncio.run(run_hi())
    assert c.last_write_stats()["events"] == 0
    assert c.temporal_memory.count() == 0

    # 模型已写记忆 → 不重复兜底（让 ScriptedModel 真的调 remember_event）
    model_with_write = ScriptedModel([
        ModelResponse(content="", tool_calls=[ToolCallRequest(
            id="m1", name="remember_event",
            arguments={"what": "I have 3 sisters", "speaker": "user"},
        )]),
        ModelResponse(content="已记住"),
    ])
    d = YoAiAgent(model=model_with_write, data_dir=tmp_path / "dup", memory_fallback=True)
    async def run_dup():
        async for _ in d.astream("I have 3 sisters and I live in Beijing"):
            pass
    asyncio.run(run_dup())
    stats = d.last_write_stats()
    assert stats["model"] >= 1, stats
    assert stats["fallback"] == 0, stats   # 模型写了，兜底不触发
    assert d.temporal_memory.count() == stats["events"]   # 没有重复写
