"""外部智能体接入契约 — PeerAdapter。

设计原则（见 docs/COMMUNICATION-PLAN.md 阶段 C + docs/AGENT-PROBE.md 探测结论）：
- 统一接口容纳三种接入级别：L2 真接入 / L1 仅唤起 / L0 未发现接口。
- 外部调用一律 fail closed：带超时、可禁用、缺配置不冒充可用。
- 对齐 Core 的 A2A 客户端思路（send(task) -> 结果），不另造 RPC 框架。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdapterResult:
    """一次外部投递的结果。"""

    ok: bool
    text: str = ""
    level: str = "L2"          # L2 / L1 / L0
    detail: str = ""           # 诊断信息（警告/超时/需人工转发说明）
    meta: dict[str, Any] = field(default_factory=dict)
    # 真实模型工具调用：每项 {"id": str, "name": str, "arguments": dict}
    # 纯文本适配器/L1 留空，不影响既有行为
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class PeerAdapter(ABC):
    """一个外部智能体的接入适配器。子类只需实现 send 与 available。"""

    level: str = "L0"          # 由子类覆盖

    def __init__(self, name: str, *, enabled: bool = True, timeout_s: float = 60.0) -> None:
        self.name = name
        self.enabled = enabled
        self.timeout_s = timeout_s

    @abstractmethod
    def available(self) -> bool:
        """该智能体在当前机器是否真的可用（命令存在 / 配置齐全）。"""

    @abstractmethod
    def send(self, message: str) -> AdapterResult:
        """把一条消息投递给该智能体，返回结果。不得抛异常到调用方。"""

    def capabilities(self) -> list[str]:
        """能力声明，供通道展示与授权判断。"""
        return []

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "available": self.available(),
            "enabled": self.enabled,
            "capabilities": self.capabilities(),
        }
