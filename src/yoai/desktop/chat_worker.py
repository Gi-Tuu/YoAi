"""通讯页消息发送 worker：在后台 asyncio 循环里驱动 channel.send。

channel.send 会并发调用多个 peer 的 Core 循环，耗时可能长，必须放后台线程；
产生的每条消息（原消息 + 各 peer 回复）通过 signal 回 UI。
"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QThread, Signal

from yoai.chat import Channel, Message


class ChannelWorker(QThread):
    message_produced = Signal(object)  # Message
    send_done = Signal(int)            # 产生的消息条数
    send_error = Signal(str)

    def __init__(self, channel: Channel, message: Message, parent=None) -> None:
        super().__init__(parent)
        self._channel = channel
        self._message = message

    def requestInterruption(self) -> None:  # noqa: N802 - Qt 方法名
        """真正中断：Qt 标志 + 取消 asyncio 任务（否则关窗后线程残留）。"""
        super().requestInterruption()
        task = getattr(self, "_asyncio_task", None)
        loop = getattr(self, "_loop", None)
        if task is not None and loop is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)

    def run(self) -> None:  # noqa: D102
        self._loop: asyncio.AbstractEventLoop | None = None
        self._asyncio_task: asyncio.Task | None = None

        async def _main() -> list:
            self._loop = asyncio.get_running_loop()
            self._asyncio_task = asyncio.current_task()
            return await self._channel.send(self._message)

        try:
            produced = asyncio.run(_main())
            for msg in produced:
                self.message_produced.emit(msg)
            self.send_done.emit(len(produced))
        except asyncio.CancelledError:
            return   # 关窗取消，不是错误
        except Exception as exc:  # noqa: BLE001 - 线程内兜住，不拖垮 UI
            self.send_error.emit(f"{type(exc).__name__}: {exc}")
