"""审批通道测试：auto 权限档真弹窗、失败关闭。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.policy import AllowlistPolicy
from yai_core.policy.authorize import authorize_tool_call

from yoai.desktop.approval import ApprovalChannel

app = QApplication.instance() or QApplication([])


def test_confirm_waits_for_main_thread_answer():
    ch = ApprovalChannel()
    seen = {}

    def on_request(tool, shown, loop, future):
        seen["tool"] = tool
        seen["shown"] = shown
        loop.call_soon_threadsafe(_answer, future, True)   # 模拟主线程点了"同意"

    ch.confirm_requested.connect(on_request)

    async def run():
        return await ch.confirm("file_create", {"path": "notes/a.txt"}, {"reason": "写文件"})

    result = asyncio.run(run())
    assert result is True
    assert seen["tool"] == "file_create"
    assert "写文件" in seen["shown"]


def _answer(future, value):
    from yoai.desktop.approval import set_future
    set_future(future, value)


def test_shutdown_rejects_pending():
    ch = ApprovalChannel()
    results = {}

    def on_request(tool, shown, loop, future):
        results["future"] = future
        ch.shutdown.emit()   # 模拟关窗：直接发 shutdown

    ch.confirm_requested.connect(on_request)

    async def run():
        return await ch.confirm("file_patch", {"path": "a"})

    assert asyncio.run(run()) is False   # 关窗 = 拒绝，绝不默认放行


def test_allowlist_auto_vs_confirm():
    """auto 档：白名单工具自动过；白名单外走 confirm（由 channel 决定）。"""
    class DenyChannel:
        async def confirm(self, tool, args, *a):
            return False

    policy = AllowlistPolicy(allowed={"file_read"}, mode="auto")
    _, approved, _ = asyncio.run(authorize_tool_call(policy, DenyChannel(), "file_read", {}))
    assert approved is True   # 白名单内，不问
    _, denied, _ = asyncio.run(authorize_tool_call(policy, DenyChannel(), "file_create", {}))
    assert denied is False    # 白名单外，问了被拒
