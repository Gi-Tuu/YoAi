"""单实例守卫测试：同进程内第二个 guard 必须拿不到实例。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.desktop.single_instance import SingleInstanceGuard

app = QApplication.instance() or QApplication([])


def test_second_guard_is_rejected():
    name = "yoai-test-single-instance-1"
    g1 = SingleInstanceGuard(name)
    assert g1.acquire() is True
    try:
        g2 = SingleInstanceGuard(name)
        assert g2.acquire() is False, "第二个实例不应启动"
    finally:
        g1.release()
    # 释放后新的可以启动（模拟进程退出后重启）
    g3 = SingleInstanceGuard(name)
    assert g3.acquire() is True
    g3.release()


def test_self_check_detection(monkeypatch):
    from yoai.desktop import single_instance
    monkeypatch.setattr(single_instance.os, "sys", type("S", (), {"argv": ["YoAi.exe", "--self-check"]})())
    assert single_instance.is_self_check() is True
