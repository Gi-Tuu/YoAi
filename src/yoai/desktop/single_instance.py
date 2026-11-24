"""桌面端单实例守卫（2026-11-24）。

用 Qt 的 QLocalServer/QLocalSocket 而非 PID 文件：
- 进程退出/崩溃时 socket 由 OS 自动释放，不会有"陈旧锁"残留（PID 文件会）
- 无 PID 复用误判
- 跨平台，exe 与源码模式都生效

约定：只允许一个 YoAi 桌面实例。第二个启动时检测到已有实例即静默退出。
"""
from __future__ import annotations

import os
from typing import Any

SERVER_NAME = "yoai-desktop-single-instance"


class SingleInstanceGuard:
    """持有 QLocalServer 直到进程退出；第二实例 acquire() 返回 False。

    用法（在 QApplication 创建之后、建窗口之前）：
        guard = SingleInstanceGuard()
        if not guard.acquire():
            return 0   # 已有实例，直接退出
        ... 建窗口 ...
        # guard 由对象析构/进程退出自动释放

    self-check 用 bypass 参数跳过（自检是独立进程，可与桌面并存）。
    """

    def __init__(self, name: str = SERVER_NAME) -> None:
        self.name = name
        self._server: Any | None = None

    def acquire(self) -> bool:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket

        # 先探测：能连上 = 已有实例在跑
        probe = QLocalSocket()
        probe.connectToServer(self.name)
        if probe.waitForConnected(300):
            probe.disconnectFromServer()
            return False
        probe.deleteLater()

        # 清掉上次崩溃残留的 socket 路径（QLocalServer 静态 API）
        QLocalServer.removeServer(self.name)
        server = QLocalServer()
        if not server.listen(self.name):
            return False   # 抢不到 = 别的实例刚占了
        self._server = server
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:  # noqa: BLE001 - 析构不能抛
            pass


def is_self_check() -> bool:
    return "--self-check" in os.sys.argv
