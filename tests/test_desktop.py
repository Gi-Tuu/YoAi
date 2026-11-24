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
    win._on_done('已处理。结果：<tool_output untrusted="true">已记住你的偏好。</tool_output>')
    texts = [win.trace.item(i).text() for i in range(win.trace.count())]
    assert any("路由" in t and "react" in t for t in texts)
    assert any("调用工具" in t and "remember_fact" in t for t in texts)
    assert "[YoAi] 已处理。结果：已记住你的偏好。" in win.chat.toPlainText()
    assert "<tool_output" not in win.chat.toPlainText()
    assert win.send_btn.isEnabled() is True
    win.close()


def test_markdown_and_process_block_render(app, tmp_path):
    """Markdown 渲染 + 过程块（thinking/工序运行时展开、DONE 后折叠）。"""
    from yoai.desktop.markdown_html import md_to_html

    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    win = MainWindow(agent)

    win.chat.add_message("YoAi", "**已记住**深色主题")
    html = win.chat.toHtml()
    assert "font-weight:600" in html and "已记住" in html
    assert "**已记住**" not in html

    win.chat.add_message("我", "**这不是markdown**")
    assert "**这不是markdown**" in win.chat.toHtml()

    idx = win.chat.begin_process("YoAi")
    win.chat.add_process_line(idx, "正在核对偏好", "think")
    win.chat.add_process_line(idx, "调用 remember_fact", "step")
    assert "正在核对偏好" in win.chat.toHtml()   # 运行时展开可见
    win.chat._messages[idx].text = "已记住深色主题"
    win.chat.collapse_process(idx)
    collapsed = win.chat.toHtml()
    assert "点击展开" in collapsed and "2 条记录" in collapsed
    assert "正在核对偏好" not in collapsed      # 折叠后过程隐藏
    win.close()


def test_process_block_wired_to_events(app, tmp_path):
    """thinking 事件写进正文过程块；done 后自动折叠。"""
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    win = MainWindow(agent)
    win._process_index = win.chat.begin_process("YoAi")
    win._on_event("thinking", {"text": "用户问的是主题偏好"})
    win._on_event("tool_call", {"tool": "recall_fact", "arguments": {}})
    assert "用户问的是主题偏好" in win.chat.toHtml()
    win._on_done('| 键 | 值 |\n|---|---|\n| 主题偏好 | 深色主题 |')
    html = win.chat.toHtml()
    assert "点击展开" in html and "主题偏好" in html
    assert "<table" in html   # 表格语法渲染
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


def test_chat_detail_tiles_preserve_chat_width(app, tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    win = MainWindow(agent)
    win.show()
    assert win.palette.name == "light"
    assert win.nav.buttons["chat"].isChecked()
    for width in (1180, 980):
        win.resize(width, 640)
        app.processEvents()
        assert not win.inspector.isVisible()
        assert not win.inspector_toggle_btn.isVisible()
        before = win.chat.width()
        assert len(win.detail_tiles) == 4
        for tile, popup in win.detail_tiles:
            assert tile.isVisible()
            tile.click()
            app.processEvents()
            assert popup.isVisible()
            assert win.chat.width() == before
            popup.close()
    win.close()


def test_communication_uses_context_inspector(app, tmp_path):
    from yoai.demo_world import build_demo_channel

    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "main")
    channel = build_demo_channel(tmp_path / "chat")
    win = MainWindow(agent, channel=channel)
    win.tabs.setCurrentIndex(1)
    assert win.inspector_title.text() == "会话检查器"
    assert win.nav.buttons["communication"].isChecked()
    assert not win.inspector.isHidden()
    win.close()


def test_memory_summary_reads_real_write_stats(app, tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path)
    win = MainWindow(agent)
    agent.temporal_memory.write_stats.update({"calls": 1, "events": 1, "fallback": 1})
    win._refresh_memory_summary()
    assert "本轮记忆 +1" in win.memory_summary.value.text()
    assert "规则兜底" in win.memory_summary.source.text()
    win.close()


def test_composer_enter_and_shift_enter(app):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from yoai.desktop.widgets import Composer

    composer = Composer()
    sent = []
    composer.returnPressed.connect(lambda: sent.append(composer.text()))
    composer.setText("第一行")
    cursor = composer.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    composer.setTextCursor(cursor)
    QTest.keyClick(composer, Qt.Key.Key_Return)
    assert sent == ["第一行"]
    QTest.keyClick(composer, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert sent == ["第一行"]
    assert composer.text() == "第一行\n"
    composer.close()
