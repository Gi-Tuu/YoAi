"""Channel — 通讯总线：注册 peer、建群、点对点与群广播、落盘、防循环。

设计要点：
- 点对点：recipient 是 peer id → 投递给该 peer；若 kind=chat 则触发其回复。
- 群广播：recipient 是群 id → 展开为对每个成员投递；发送者自己不重复收。
- 防循环：只有 kind=chat 触发 peer 自动回复；reply/system 只投递不触发，
  否则 A 回复 B、B 又回 A 会无限循环。
- 所有消息落盘（ChatStore），跨会话可查。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from yoai.chat.models import Group, Message
from yoai.chat.peer import AgentPeer
from yoai.chat.store import ChatStore


class Channel:
    """一个通讯通道：管理 peer 与群，路由消息。"""

    def __init__(self, store: ChatStore, on_message: Callable[[Message], None] | None = None):
        self.store = store
        self.peers: dict[str, AgentPeer] = {}
        self.on_message = on_message  # UI 订阅：每条消息（含回复）都会回调

    def register(self, peer: AgentPeer) -> bool:
        if peer.id in self.peers:
            return False
        self.peers[peer.id] = peer
        return True

    def unregister(self, peer_id: str) -> bool:
        return self.peers.pop(peer_id, None) is not None

    def create_group(self, name: str, member_ids: list[str]) -> Group:
        valid = [pid for pid in member_ids if pid in self.peers]
        group = Group.create(name, valid)
        self.store.save_group(group)
        return group

    def add_member(self, group_id: str, peer_id: str) -> bool:
        group = self.store.get_group(group_id)
        if not group or peer_id not in self.peers:
            return False
        ok = group.add_member(peer_id)
        if ok:
            self.store.save_group(group)
        return ok

    def groups(self) -> list[Group]:
        return self.store.groups()

    def history(self, channel: str = "") -> list[Message]:
        return self.store.messages(channel=channel)

    def _emit(self, message: Message) -> None:
        self.store.append_message(message)
        if self.on_message:
            self.on_message(message)

    async def send(self, message: Message) -> list[Message]:
        """发送一条消息，返回过程中产生的所有消息（原消息 + 各 peer 回复）。

        群广播时回复的默认接收方是群（群里所有人可见），避免点对点回单个成员
        造成信息不对称；点聊时回复给发送者。
        """
        produced: list[Message] = [message]
        self._emit(message)

        group = next((g for g in self.groups() if g.id == message.recipient), None)
        if group:
            # 群广播：投递给每个成员（排除发送者本人）
            targets = [pid for pid in group.members if pid != message.sender]
        else:
            targets = [message.recipient] if message.recipient in self.peers else []

        if message.kind != "chat":
            return produced  # reply/system 不触发自动回复，防循环

        # 并发投递给各目标 peer（各自独立实例，可并行）
        replies = await asyncio.gather(
            *(self._deliver_and_reply(message, target, group.id if group else "") for target in targets),
            return_exceptions=True,
        )
        for reply in replies:
            if isinstance(reply, Message):
                produced.append(reply)
            elif isinstance(reply, BaseException):
                # 单个 peer 失败不影响其它成员，发一条 system 错误消息
                err = Message.create("system", message.recipient, f"peer 处理失败：{reply}", kind="system")
                self._emit(err)
                produced.append(err)
        return produced

    async def _deliver_and_reply(self, message: Message, target_id: str, group_id: str) -> Message:
        peer = self.peers[target_id]
        reply_text = await peer.handle(message)
        reply_to = group_id if group_id else message.sender
        reply = Message.create(target_id, reply_to, reply_text, kind="reply",
                               meta={"in_reply_to": message.id, "peer_name": peer.name})
        self._emit(reply)
        return reply
