"""桌面会话选择 UI 测试（offscreen）：下拉列表、切换、新建、历史重载。"""

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
from yai_core import ModelResponse, ScriptedModel  # noqa: E402

from yoai.desktop.main_window import MainWindow  # noqa: E402
from yoai.session import SessionManager  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _factory():
    return ScriptedModel([ModelResponse(content="回答")])


def test_window_has_session_selector(app, tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory)
    mgr.create("会话一")
    win = MainWindow(mgr.current_agent(), session_manager=mgr)
    assert win.session_combo.count() == 1
    assert "会话一" in win.session_combo.itemText(0)
    win.close()


def test_new_session_button(app, tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory)
    mgr.create("会话一")
    win = MainWindow(mgr.current_agent(), session_manager=mgr)
    win._on_new_session()
    assert win.session_combo.count() == 2
    assert mgr.current is not None
    win.close()


def test_switch_session(app, tmp_path):
    mgr = SessionManager(tmp_path, model_factory=_factory)
    s1 = mgr.create("A")
    s2 = mgr.create("B")
    win = MainWindow(mgr.current_agent(), session_manager=mgr)
    # 切回 A（s2 是当前，index 0 是 A）
    idx = win.session_combo.findData(s1.id)
    win.session_combo.setCurrentIndex(idx)
    assert mgr.current.id == s1.id
    win.close()


def test_no_session_selector_without_manager(app, tmp_path):
    from yoai.agent import YoAiAgent
    agent = YoAiAgent(model=_factory(), data_dir=tmp_path)
    win = MainWindow(agent)  # 不传 session_manager
    assert not hasattr(win, "session_combo") or win.session_combo is None
    win.close()
