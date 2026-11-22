"""桌面端 offscreen 测试：验证窗口构建与事件流→UI 的完整闭环。

用 QT_QPA_PLATFORM=offscreen，无需真实显示器，CI 可跑。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:\Competition\YAI Agent Core") / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.demo_model import DemoModel  # noqa: E402
from yoai.desktop.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_builds(app, tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    win = MainWindow(agent)
    assert win.windowTitle() == "YoAi"
    assert win.chat is not None
    assert win.trace is not None
    assert win.facts is not None
    assert win.goals is not None
    win.close()


def test_event_rendering_updates_trace_and_chat(app, tmp_path):
    from yoai.desktop.worker import AgentWorker

    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    win = MainWindow(agent)
    # 直接渲染事件，验证 UI 映射逻辑（不依赖线程时序）
    win._on_event("strategy_selected", {"strategy": "react"})
    win._on_event("tool_call", {"tool": "remember_fact", "arguments": {"key": "theme"}})
    win._on_done("已记住你的偏好。")
    texts = [win.trace.item(i).text() for i in range(win.trace.count())]
    assert any("路由" in t and "react" in t for t in texts)
    assert any("调用工具" in t and "remember_fact" in t for t in texts)
    assert "[YoAi] 已记住你的偏好。" in win.chat.toPlainText()
    assert win.send_btn.isEnabled() is True
    win.close()


def test_worker_signal_drives_real_loop(app, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    win = MainWindow(agent)
    win.input.setText("记住我偏好深色主题")
    win._on_send()

    # 等 worker 完成（最多 5s）
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    win.worker.task_done.connect(lambda _: loop.quit())
    if win.worker.isRunning():
        loop.exec()
    timer.stop()

    assert agent.context.count() >= 1
    assert "[YoAi]" in win.chat.toPlainText()
    assert win.trace.count() >= 2
    win.close()
