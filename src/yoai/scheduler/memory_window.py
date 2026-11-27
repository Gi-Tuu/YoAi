"""S5-3：定时任务每次运行用全新的上下文（对齐 OpenClaw 的 isolated 任务）。

OpenClaw 的 isolated 任务每次运行都开一个新会话。YoAi 想保留一个统一的「⏰ 定时任务」
会话方便用户回看结果，所以换个做法：包装该会话的 memory，**运行期间** ``history()``
只返回本次运行开始之后的消息——模型看不到之前每次运行的对话；运行结束后恢复完整视图，
界面照常显示全部历史。新消息照常写入底层存储，什么都不丢。

依据：Core 的 AgentLoop 每轮从 ``memory.history()`` 读上下文、用 ``append_history`` 写入
（与 ``conversation_actions.ConversationMemory`` 依赖的接口相同）。其余属性原样委派。
个人事实 / 目标 / 事件记忆不在这里，照常共享——"记住的东西"跨运行仍然有效。
"""

from __future__ import annotations

from typing import Any


class RunWindowMemory:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._start: int | None = None

    # ---- 运行窗口 ----
    def begin(self) -> None:
        self._start = len(list(self._inner.history()))

    def end(self) -> None:
        self._start = None

    @property
    def windowed(self) -> bool:
        return self._start is not None

    # ---- Core 使用的接口 ----
    def history(self) -> list[Any]:
        messages = list(self._inner.history())
        return messages if self._start is None else messages[self._start:]

    def history_with_indices(self) -> list[tuple[int, Any]]:
        if hasattr(self._inner, "history_with_indices"):
            pairs = list(self._inner.history_with_indices())
        else:
            pairs = list(enumerate(self._inner.history()))
        return pairs if self._start is None else pairs[self._start:]

    async def append_history(self, message: Any) -> None:
        await self._inner.append_history(message)

    def __getattr__(self, name: str) -> Any:
        # put / get / clear / history_full 等其余接口原样委派
        if name in ("_inner", "_start"):      # 构造前被访问（如 copy）时不要无限递归
            raise AttributeError(name)
        return getattr(self._inner, name)
