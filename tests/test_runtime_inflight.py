"""S5-2 runtime 接线：被打断的对话轮次（真实 yoai_runtime + 假 agent，不联网）。

复用 test_e2e_journey 的假件。需要 Core（yoai_runtime 导入时依赖）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_e2e_journey import FakeAgent, collect, make_runtime  # noqa: E402
from yoai.inflight import InflightTurns  # noqa: E402


class SlowAgent(FakeAgent):
    """一直卡着不结束，直到 gate 放行。"""

    def __init__(self) -> None:
        super().__init__([("done", {"final_text": "完成"})])
        self.gate = asyncio.Event()

    async def astream(self, task: str):
        await self.gate.wait()
        yield SimpleNamespace(type=SimpleNamespace(value="done"), data={"final_text": "完成"})


def _runtime(tmp_path, agent=None):
    rt = make_runtime(store_dir=tmp_path)
    if agent is not None:
        rt.agent = agent
        rt.sessions._agent = agent
    rt.inflight = InflightTurns(tmp_path)
    return rt, collect(rt)


def test_finished_turn_is_not_reported(tmp_path):
    async def main():
        rt, _out = _runtime(tmp_path)
        await rt.handle({"type": "task.start", "task_id": "t1", "run_id": "r1", "input": "你好"})
        await asyncio.gather(*rt.tasks.values(), return_exceptions=True)
    asyncio.run(main())
    assert InflightTurns(tmp_path).interrupted() == []


def test_shutdown_mid_turn_is_reported_next_time(tmp_path):
    async def main():
        rt, _out = _runtime(tmp_path, SlowAgent())
        await rt.handle({"type": "task.start", "task_id": "t1", "run_id": "r1", "input": "写一份周报"})
        await asyncio.sleep(0.01)
        assert await rt.handle({"type": "shutdown"}) is False      # 关应用
        await asyncio.gather(*rt.tasks.values(), return_exceptions=True)
    asyncio.run(main())

    async def next_start():
        rt, out = _runtime(tmp_path)                                  # 下次打开
        await rt.handle({"type": "hello"})
        msg = next(m for m in out if m["type"] == "task.interrupted")
        assert [i["input"] for i in msg["items"]] == ["写一份周报"]
        assert msg["items"][0]["session_name"] == "新会话"
        await rt.handle({"type": "task.interrupted_dismiss", "run_id": "r1"})
        last = [m for m in out if m["type"] == "task.interrupted"][-1]
        assert last["items"] == []
    asyncio.run(next_start())
    assert InflightTurns(tmp_path).interrupted() == []


def test_user_stop_is_not_an_interruption(tmp_path):
    async def main():
        rt, _out = _runtime(tmp_path, SlowAgent())
        await rt.handle({"type": "task.start", "task_id": "t1", "run_id": "r1", "input": "x"})
        await asyncio.sleep(0.01)
        await rt.handle({"type": "task.cancel", "task_id": "t1", "run_id": "r1"})   # 用户点停止
        await asyncio.gather(*rt.tasks.values(), return_exceptions=True)
    asyncio.run(main())
    assert InflightTurns(tmp_path).interrupted() == []
