"""AgentPeer — 一个接入 YoAi 通讯通道的智能体。

每个 peer 持有自己独立的 YoAiAgent 实例（Core 并发契约：一实例一会话，
要并发就多实例），因此多个 peer 可同时处理各自收到的消息、互不污染状态。
"""

from __future__ import annotations

from typing import Any

from yoai.agent import YoAiAgent
from yoai.chat.models import Message


class AgentPeer:
    """通讯通道中的一个智能体节点。"""

    def __init__(self, peer_id: str, name: str, agent: YoAiAgent) -> None:
        self.id = peer_id
        self.name = name
        self.agent = agent

    async def handle(self, message: Message) -> str:
        """处理一条收到的 chat 消息，返回要回复的文本。

        复用 YoAiAgent 的完整 Core 事件循环：消息内容作为任务交给该 peer 的模型，
        因此 peer 可以调用自己的工具（记住偏好、建目标等），回复是真实执行结果。
        """
        from yai_core import EventType

        final_text = ""
        async for event in self.agent.astream(message.content):
            if event.type == EventType.DONE:
                final_text = str(event.data.get("final_text", ""))
        return final_text or "（无回复）"

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "tools": self.agent.list_tools()}
