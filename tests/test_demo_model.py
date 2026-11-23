"""DemoModel 驱动的端到端工具闭环测试（离线）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core import EventType  # noqa: E402

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.demo_model import DemoModel  # noqa: E402


def _run(agent, text):
    async def go():
        events = []
        async for e in agent.astream(text):
            events.append(e)
        return events

    return asyncio.run(go())


def test_demo_remembers_fact(tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    events = _run(agent, "记住我偏好深色主题")
    assert any(e.type == EventType.TOOL_CALL for e in events)
    assert any(e.type == EventType.DONE for e in events)
    # 意图解析：key=我偏好深色主题? 检查任一 fact 落盘
    assert agent.context.count() >= 1


def test_demo_creates_goal(tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    events = _run(agent, "创建一个目标：完成 YoAi 原型")
    assert agent.goals.count() >= 1
    assert any(e.type == EventType.DONE for e in events)


def test_demo_lists_goals(tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    _run(agent, "创建一个目标：测试")
    n_before = agent.goals.count()
    events = _run(agent, "列出我的目标")
    assert any(e.type == EventType.TOOL_CALL for e in events)
    assert agent.goals.count() == n_before
    done = [e for e in events if e.type == EventType.DONE][0]
    assert "测试" in done.data["final_text"]


def test_demo_chat_without_tool(tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    events = _run(agent, "你好")
    done = [e for e in events if e.type == EventType.DONE][0]
    assert "YoAi" in done.data["final_text"]
