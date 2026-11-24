"""桌面审批通道（2026-11-24）：把 Core 的权限策略真正接到用户弹窗。

Core 的 AllowlistPolicy(mode="auto") 遇到白名单外工具会调 channel.confirm()。
默认 CollectChannel(auto_confirm=True) 永远返回 True——审批形同虚设。
本通道让 confirm() 真等用户点确认：

- confirm() 在 worker 线程的 asyncio loop 里 await
- 通过 Qt Signal 把请求送到主线程（GUI 只能在主线程弹）
- 主线程弹 QMessageBox，把结果用 loop.call_soon_threadsafe 写回 Future
- 用户在弹窗前关窗口 → 主线程析构时把所有 pending Future 置 False（失败关闭）

用法：YoAiAgent(channel=ApprovalChannel()) → AgentCore(channel=...)
      MainWindow 连接 channel.confirm_requested 到自己的弹窗槽。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from PySide6.QtCore import QObject, Signal

# 声明支持审批上下文（Core 的 ApprovalContextChannel 能力旗标）
_YAI_APPROVAL_CONTEXT_AWARE = True


class ApprovalChannel(QObject):
    """Core Channel 实现：confirm() 等主线程弹窗结果。"""

    # (tool_name, shown_args_json, loop, future)
    confirm_requested = Signal(str, str, object, object)
    # 主窗口关闭时发这个，让所有 pending confirm 立即失败关闭
    shutdown = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.yai_approval_context_aware = _YAI_APPROVAL_CONTEXT_AWARE
        self._pending: set[asyncio.Future] = set()
        self.shutdown.connect(self._on_shutdown)

    async def emit(self, event: Any) -> None:
        pass   # 事件由 worker 的 event_received 单独发给 UI，不走这里

    async def ask(self, question: str) -> str:
        return ""   # 澄清走 Core 的 clarify 事件，桌面暂不在此弹窗

    async def confirm(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending.add(future)
        try:
            # 参数已由 Core 脱敏；只送展示用的字段给主线程
            shown = {
                "arguments": arguments,
                **{k: v for k, v in (context or {}).items()
                   if k in ("prompt", "reason", "target", "risk", "scope", "preview")},
            }
            self.confirm_requested.emit(
                tool_name,
                json.dumps(shown, ensure_ascii=False, default=str),
                loop,
                future,
            )
            return bool(await future)
        finally:
            self._pending.discard(future)

    def _on_shutdown(self) -> None:
        """窗口关闭：所有等待中的审批一律拒绝（绝不默认放行）。"""
        for future in list(self._pending):
            if not future.done():
                loop = future.get_loop()
                loop.call_soon_threadsafe(_resolve_false, future)


def _resolve_false(future: asyncio.Future) -> None:
    if not future.done():
        future.set_result(False)


def set_future(future: asyncio.Future, value: Any) -> None:
    """线程安全地回填审批结果（供 UI 主线程调用）。"""
    if not future.done():
        future.set_result(value)
