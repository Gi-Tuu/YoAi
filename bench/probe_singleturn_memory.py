"""单轮低温记忆抽取可行性验证（不改生产代码）。

问题：评测的 +8.8pp 靠"批量历史 + 低温 + 独立记忆调用"，生产是"单轮用户输入"。
本实验验证：单轮输入 + 低温 0.1 + 评测同款 prompt，能否稳定触发 remember_event 并记对事实。

对比：温度 [默认(None), 0.1] × 单轮消息 10 条。
输出：每条的记忆条数、是否触发工具、事实是否正确（人工看）。
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Core 源码根目录：环境变量优先，否则从 PYTHONPATH 已注入的路径复用
if not any((Path(p) / "yai_core").is_dir() for p in sys.path if p):
    import os
    _core = os.environ.get("YAI_CORE_SRC")
    if _core and (Path(_core) / "src" / "yai_core").is_dir():
        sys.path.insert(0, str(Path(_core) / "src"))

from yai_core import EventType  # noqa: E402
from yai_core.tools import ToolRegistry  # noqa: E402
from yoai.agent import YoAiAgent  # noqa: E402
from yoai.models import GatewayModelProvider, SuanliAdapter  # noqa: E402
from yoai.temporal_memory import TemporalMemory  # noqa: E402

# 10 条带明确事实的单轮用户消息（数字/名字/时间/偏好），答案可核对
SINGLE_TURNS = [
    "I just started a new job at Acme Corp. My commute is 45 minutes now.",
    "My sister has three kids and we are going camping next weekend to Lake Tahoe.",
    "I bought a used Toyota Camry for $12,000 last month.",
    "I prefer oat milk in my coffee, never regular milk.",
    "My birthday is March 15 and I was born in 1992.",
    "I have two dogs, a golden retriever named Max and a cat named Luna.",
    "I moved to Seattle in June 2021 and I love the rainy weather here.",
    "My favorite book is Dune by Frank Herbert, I've read it three times.",
    "I'm allergic to peanuts, so please never suggest peanut recipes.",
    "I run about 5 miles every morning before work.",
]

# 复刻评测同款记忆 prompt 结构（中文触发词是关键——原文实测能触发工具）
MEMORY_PROMPT = (
    "请从下面这条用户消息中提取事实，用 remember_event 工具逐条记下来"
    "（数字、名字、时间、地点、偏好、所有物）。speaker 填 user，"
    "每条给 event_time 和 topics。不要记寒暄。记完回复你记了几条。\n\n用户消息：\n{msg}"
)


async def extract_one(msg: str, temp: float | None) -> dict:
    tmp = Path(tempfile.mkdtemp())
    tmem = TemporalMemory(tmp / "t.json")
    adapter = SuanliAdapter(temperature=temp)
    agent = YoAiAgent(
        model=GatewayModelProvider(adapter), data_dir=tmp / "ctx", temporal_memory=tmem,
    )
    # 复刻评测：替换 registry 只留 remember_event（保证模型不用别的工具）
    only = ToolRegistry()
    for s in agent.core.registry.all():
        if getattr(s, "name", "") == "remember_event":
            only.register(s)
    agent.core.registry = only

    tool_calls = 0
    async for event in agent.astream(MEMORY_PROMPT.format(msg=msg)):
        if event.type == EventType.TOOL_CALL:
            tool_calls += 1
    facts = [e["what"] for e in tmem.timeline()]
    return {"temp": temp, "tool_calls": tool_calls, "facts": facts}


async def main():
    for temp in (None, 0.1):
        label = "默认" if temp is None else str(temp)
        print(f"\n===== temperature={label} =====", flush=True)
        total_facts = 0
        triggered = 0
        for i, msg in enumerate(SINGLE_TURNS, 1):
            r = await extract_one(msg, temp)
            total_facts += len(r["facts"])
            if r["tool_calls"] > 0:
                triggered += 1
            print(f"[{i:2}] tools={r['tool_calls']} facts={len(r['facts'])} | {msg[:42]}", flush=True)
            for f in r["facts"][:3]:
                print(f"       - {f[:65]}", flush=True)
        print(f"小计: 触发 {triggered}/10 条, 共记 {total_facts} 条, 平均 {total_facts/10:.1f} 条/条",
              flush=True)


if __name__ == "__main__":
    asyncio.run(main())
