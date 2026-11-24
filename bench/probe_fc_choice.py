"""诊断：讯飞在真实场景下各轮 tool schema 与输出格式。"""
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

orig = GatewayModelProvider.achat
rounds: list[tuple[int, int, int, str]] = []  # (轮次, 消息数, tools数, 输出类型)


async def traced(self, messages, tools=None, *, tier="standard"):
    r = await orig(self, messages, tools, tier=tier)
    content = str(r.content or "")
    kind = ("DSML" if "<tool_call" in content else
            f"tool_calls({len(r.tool_calls or [])})" if r.tool_calls else
            f"text({len(content)})")
    rounds.append((len(rounds) + 1, len(messages), len(tools or []), kind))
    return r


GatewayModelProvider.achat = traced

with tempfile.TemporaryDirectory() as d:
    a = YoAiAgent(model=GatewayModelProvider(SuanliAdapter()), data_dir=d,
                  temporal_memory=False)
    async def run():
        async for _ in a.astream("记住我偏好深色主题"):
            pass
    asyncio.run(run())

for rnd, nmsg, ntools, kind in rounds:
    print(f"轮{rnd}: messages={nmsg} tools={ntools} 输出={kind}")
