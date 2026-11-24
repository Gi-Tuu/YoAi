"""SidecarChannel 构造辅助：复用 Core 公开 SPI，不改内核。

Core 的 yai_core.sidecar.channel.SidecarChannel 已实现 approval/clarify
转发与超时降级；这里只把 runtime 的 _request_host 回调绑进去。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def make_sidecar_channel(
    request_host: Callable[[str, dict[str, Any]], Awaitable[Any]],
    *, timeout: float = 600.0,
) -> Any:
    from yai_core.sidecar.channel import SidecarChannel
    return SidecarChannel(request_host, timeout=timeout)
