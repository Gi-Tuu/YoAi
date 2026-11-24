"""桌面退出测试：worker 必须能真正取消卡住的任务（进程残留根因）。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.desktop.chat_worker import ChannelWorker
from yoai.desktop.worker import AgentWorker


app = QApplication.instance() or QApplication([])


def test_agent_worker_cancel_stops_blocking_task():
    """worker.requestInterruption 必须取消卡在 await 的协程。"""
    state = {"cancelled": False}

    class FakeAgent:
        async def astream(self, task):
            try:
                await asyncio.sleep(60)   # 模拟卡住的网络调用
                yield None
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

    w = AgentWorker(FakeAgent(), "测试")
    w.start()
    # 等任务真正进入 asyncio.sleep
    import time
    deadline = time.time() + 3
    while getattr(w, "_asyncio_task", None) is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert w._asyncio_task is not None, "task 没启动"
    w.requestInterruption()
    w.wait(3000)
    assert not w.isRunning(), "取消后 worker 仍活着 → 进程残留"
    assert state["cancelled"], "协程没收到 CancelledError"


def test_channel_worker_cancel_stops_blocking_send():
    state = {"cancelled": False}

    class FakeChannel:
        async def send(self, msg):
            try:
                await asyncio.sleep(60)
                return []
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

    w = ChannelWorker(FakeChannel(), object())
    w.start()
    import time
    deadline = time.time() + 3
    while getattr(w, "_asyncio_task", None) is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert w._asyncio_task is not None
    w.requestInterruption()
    w.wait(3000)
    assert not w.isRunning(), "channel worker 仍活着"
    assert state["cancelled"]
