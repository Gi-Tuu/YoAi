"""ExternalPeer — 把 PeerAdapter 包装成 Channel 可容纳的 peer。

复用 AgentPeer 的接口形状（id / name / handle），但 handle 走外部适配器。
Channel 无需改动：对本地 peer 是 Core 循环，对外部 peer 是 CLI/协议调用。
"""

from __future__ import annotations

from typing import Any

from yoai.adapters.base import PeerAdapter
from yoai.chat.models import Message


class ExternalPeer:
    """一个由 PeerAdapter 驱动的外部智能体节点。"""

    def __init__(self, peer_id: str, adapter: PeerAdapter) -> None:
        self.id = peer_id
        self.name = adapter.name
        self.adapter = adapter

    async def handle(self, message: Message) -> str:
        """把消息交给外部智能体。

        L2：返回真实回答。
        L1：返回"需人工转发"的说明 + 投递文件路径（诚实，不伪造回答）。
        适配器异常已被 AdapterResult 吞掉，这里不再抛。
        """
        result = self.adapter.send(message.content)
        if result.ok and result.text:
            return result.text
        if result.level == "L1":
            return f"[需人工转发] {result.detail}"
        if result.level == "L0":
            return f"[未接入] {result.detail}"
        return f"[调用失败] {result.detail}"

    def describe(self) -> dict[str, Any]:
        d = self.adapter.describe()
        d.update({"id": self.id, "peer_type": "external"})
        return d
