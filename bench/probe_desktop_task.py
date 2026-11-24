"""诊断：桌面端真实任务后，chat控件实际显示什么。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer

from yoai.agent import YoAiAgent
from yoai.demo_world import build_demo_channel
from yoai.desktop.main_window import MainWindow
from yoai.models.gateway_provider import GatewayModelProvider
from yoai.models.suanli_adapter import SuanliAdapter

app = QApplication.instance() or QApplication([])
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    agent = YoAiAgent(model=GatewayModelProvider(SuanliAdapter()),
                      data_dir=root / "data", temporal_memory=False,
                      builtin_tools=True, workspace_root=root / "ws")
    channel = build_demo_channel(root / "chat")
    win = MainWindow(agent, channel=channel)

    # 用 worker 走真实事件链（和 UI 一模一样）
    from yoai.desktop.worker import AgentWorker
    worker = AgentWorker(agent, "记住我叫小明，然后直接告诉我记住了什么", win)
    worker.event_received.connect(win._on_event)
    worker.task_done.connect(win._on_done)
    worker.task_error.connect(win._on_error)

    loop = QEventLoop()
    worker.task_done.connect(lambda _: loop.quit())
    worker.task_error.connect(lambda _: loop.quit())
    QTimer.singleShot(60000, loop.quit)
    worker.start()
    loop.exec()

    print("=== chat 控件内容 ===")
    print(win.chat.toPlainText()[-600:])
    print("=== 任务状态 ===", win.task_state_label.text())
