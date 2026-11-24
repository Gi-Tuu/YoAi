"""阶段 B 群聊 UI 测试（offscreen）：标签页、会话列表、建群、消息渲染。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.demo_model import DemoModel  # noqa: E402
from yoai.demo_world import build_demo_channel  # noqa: E402
from yoai.desktop.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_has_chat_tab_and_conversations(app, tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "main")
    channel = build_demo_channel(tmp_path / "chat")
    win = MainWindow(agent, channel=channel)
    assert win.tabs.count() == 2
    assert win.tabs.tabText(0) == "我的对话"
    assert win.tabs.tabText(1) == "通讯"
    panel = win.chat_panel
    assert panel.conversations.count() == 4   # 3 peer + 1 预置群
    texts = [panel.conversations.item(i).text() for i in range(panel.conversations.count())]
    assert any("小策" in t for t in texts)
    assert any("YoAi 工作台" in t for t in texts)
    win.close()


def test_chat_panel_renders_message_once(app, tmp_path):
    from yoai.chat import Message

    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "main")
    channel = build_demo_channel(tmp_path / "chat")
    win = MainWindow(agent, channel=channel)
    panel = win.chat_panel
    # 直接渲染一条 reply，确认文本含 peer 名字
    msg = Message.create("p1", "user", "收到", kind="reply", meta={"peer_name": "小策"})
    panel._render_message(msg)
    assert "[小策] 收到" in panel.messages.toPlainText()
    assert panel.messages.toPlainText().count("[小策]") == 1
    win.close()


def test_chat_panel_send_via_worker(app, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "main")
    channel = build_demo_channel(tmp_path / "chat")
    win = MainWindow(agent, channel=channel)
    panel = win.chat_panel
    # 选第一个会话（小策）
    panel.conversations.setCurrentRow(0)
    assert panel._current_target == "p1"
    panel.chat_input.setText("你好")
    panel._on_send()

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(8000)
    if panel.worker is not None and panel.worker.isRunning():
        panel.worker.send_done.connect(lambda _: loop.quit())
        loop.exec()
    timer.stop()

    text = panel.messages.toPlainText()
    assert "[user] 你好" in text or "[user]" in text
    assert "[小策]" in text       # 收到 p1 的回复
    assert channel.store.count() >= 2
    win.close()


def test_error_event_is_visible_in_chat_and_marks_failure(app, tmp_path):
    """静默失败修复：error 事件必须显示在对话区，done 后不能标'已完成'。"""
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "main")
    channel = build_demo_channel(tmp_path / "chat")
    win = MainWindow(agent, channel=channel)

    win._task_had_error = False
    win._on_event("error", {"stage": "model_protocol", "error": "工具调用文本无法识别"})
    assert win._task_had_error is True
    # 对话区必须出现错误提示（ChatView 是 QTextBrowser，用 toPlainText 断言）
    shown = win.chat.toPlainText()
    assert "工具调用文本无法识别" in shown, shown

    win._on_done("模型说没找到记忆")
    assert "部分失败" in win.task_state_label.text()
    win.close()


def test_clean_done_without_error(app, tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "main2")
    channel = build_demo_channel(tmp_path / "chat2")
    win = MainWindow(agent, channel=channel)
    win._task_had_error = False
    win._on_done("正常回答")
    assert "已完成" in win.task_state_label.text()
    win.close()
