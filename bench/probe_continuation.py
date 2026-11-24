"""诊断：工具执行后是否自动接上对话（模型基于结果继续回答）。"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.agent import YoAiAgent
from yoai.models.gateway_provider import GatewayModelProvider
from yoai.models.suanli_adapter import SuanliAdapter
from yoai.models.gateway_provider import GatewayModelProvider as GP

# 抓每轮模型输出
orig = GatewayModelProvider.achat
async def traced(self, messages, tools=None, *, tier="standard"):
    r = await orig(self, messages, tools, tier=tier)
    kind = ("tool_calls:" + ",".join(tc.name for tc in (r.tool_calls or []))
            if r.tool_calls else "text:" + repr(str(r.content or "")[:60]))
    print(f"   [模型轮] {kind}")
    return r
GatewayModelProvider.achat = traced

with tempfile.TemporaryDirectory() as d:
    a = YoAiAgent(model=GatewayModelProvider(SuanliAdapter()), data_dir=Path(d) / "data",
                  temporal_memory=False, builtin_tools=True,
                  workspace_root=Path(d) / "ws")
    task = "先记住我叫小明，然后你直接告诉我你记住了什么"
    print("任务:", task)
    events = []
    async def run():
        async for ev in a.astream(task):
            events.append((ev.type.value, dict(ev.data or {})))
    asyncio.run(run())
    print("\n=== 事件序列 ===")
    for t, data in events:
        if t == "tool_call":
            print(f"  {t}: {data.get('tool')}")
        elif t == "tool_result":
            print(f"  {t}: {data.get('tool')} ok={data.get('ok')} preview={str(data.get('preview'))[:50]}")
        elif t == "done":
            print(f"  {t}: final_text={str(data.get('final_text'))[:120]!r}")
        elif t == "error":
            print(f"  {t}: {str(data)[:100]}")
        else:
            print(f"  {t}: {str(data)[:60]}")
