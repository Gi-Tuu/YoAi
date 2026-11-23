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
