"""YoAi 通讯内核 — 消息与群组的数据契约。

定位：Phase 1.5 阶段 A。建在 Core 之上、不侵入内核。
Core 红线不做对等 Multi-Agent 编排；这里只做"消息路由 / 群状态 / 身份"，
智能体内部怎么思考仍由各自的 YoAiAgent(Core) 决定。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Message:
    """一条通道消息。recipient 为 peer id 或群 id，由 Channel 决定如何投递。"""

    id: str
    sender: str          # 发送方 peer id；"user" 表示本地人类用户
    recipient: str       # 目标 peer id 或群 id
    content: str
    kind: str = "chat"   # chat | reply | system
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls, sender: str, recipient: str, content: str, *, kind: str = "chat",
        meta: dict[str, Any] | None = None,
    ) -> Message:
        return cls(
            id=uuid.uuid4().hex[:10],
            sender=sender,
            recipient=recipient,
            content=content,
            kind=kind,
            meta=meta or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "content": self.content,
            "kind": self.kind,
            "timestamp": self.timestamp,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            id=data["id"],
            sender=data["sender"],
            recipient=data["recipient"],
            content=data["content"],
            kind=data.get("kind", "chat"),
            timestamp=data.get("timestamp", ""),
            meta=data.get("meta", {}),
        )


@dataclass
class Group:
    """一个群：成员列表 + 群消息历史（历史由 Channel 落盘，这里只存成员）。"""

    id: str
    name: str
    members: list[str] = field(default_factory=list)   # peer id 列表
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(cls, name: str, members: list[str]) -> Group:
        return cls(id=uuid.uuid4().hex[:8], name=name, members=list(members))

    def add_member(self, peer_id: str) -> bool:
        if peer_id in self.members:
            return False
        self.members.append(peer_id)
        return True

    def remove_member(self, peer_id: str) -> bool:
        if peer_id not in self.members:
            return False
        self.members.remove(peer_id)
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "members": self.members, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Group:
        return cls(
            id=data["id"], name=data["name"],
            members=data.get("members", []),
            created_at=data.get("created_at", ""),
        )
