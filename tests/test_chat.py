"""阶段 A 通讯内核测试：点对点、群广播、拉群、防循环、持久化恢复。

全部离线（DemoModel），零 API Key。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.chat import AgentPeer, Channel, ChatStore, Message  # noqa: E402
from yoai.demo_model import DemoModel  # noqa: E402


def _make_peer(pid: str, name: str, tmp_path: Path) -> AgentPeer:
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / pid)
    return AgentPeer(pid, name, agent)


def test_register_and_group(tmp_path):
    store = ChatStore(tmp_path / "chat.json")
    ch = Channel(store)
    for pid, name in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]:
        assert ch.register(_make_peer(pid, name, tmp_path)) is True
    assert ch.register(_make_peer("a", "dupe", tmp_path)) is False

    group = ch.create_group("产品群", ["a", "b", "unknown"])
    assert group.members == ["a", "b"]          # unknown 被过滤
    assert ch.add_member(group.id, "c") is True
    assert ch.add_member(group.id, "c") is False  # 重复加失败
    assert len(ch.groups()) == 1


def test_direct_message_and_reply(tmp_path):
    store = ChatStore(tmp_path / "chat.json")
    ch = Channel(store)
    ch.register(_make_peer("a", "Alpha", tmp_path))
    ch.register(_make_peer("b", "Beta", tmp_path))

    msg = Message.create("a", "b", "你好 Beta")
    produced = asyncio.run(ch.send(msg))
    kinds = [m.kind for m in produced]
    assert kinds == ["chat", "reply"]            # 有且只有一条回复（防循环）
    reply = produced[1]
    assert reply.sender == "b" and reply.recipient == "a"
    assert reply.meta["peer_name"] == "Beta"
    assert reply.content                         # 非空回复


def test_group_broadcast_replies_from_all_members(tmp_path):
    store = ChatStore(tmp_path / "chat.json")
    ch = Channel(store)
    for pid, name in [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]:
        ch.register(_make_peer(pid, name, tmp_path))
    group = ch.create_group("全员", ["a", "b", "c"])

    produced = asyncio.run(ch.send(Message.create("a", group.id, "大家好")))
    # 1 条 chat + 来自 b、c 的 2 条 reply（发送者 a 不重复收）
    replies = [m for m in produced if m.kind == "reply"]
    assert len(replies) == 2
    assert {r.sender for r in replies} == {"b", "c"}
    assert all(r.recipient == group.id for r in replies)  # 回复进群，大家可见
    # 防循环：没有任何 reply 再触发新消息
    assert len(produced) == 3


def test_on_message_callback_sees_everything(tmp_path):
    store = ChatStore(tmp_path / "chat.json")
    seen: list[Message] = []
    ch = Channel(store, on_message=seen.append)
    ch.register(_make_peer("a", "A", tmp_path))
    ch.register(_make_peer("b", "B", tmp_path))
    asyncio.run(ch.send(Message.create("a", "b", "hi")))
    assert len(seen) == 2
    assert {m.kind for m in seen} == {"chat", "reply"}


def test_persistence_across_sessions(tmp_path):
    path = tmp_path / "chat.json"
    ch = Channel(ChatStore(path))
    ch.register(_make_peer("a", "A", tmp_path))
    ch.register(_make_peer("b", "B", tmp_path))
    group = ch.create_group("持久群", ["a", "b"])
    asyncio.run(ch.send(Message.create("a", group.id, "存下来")))

    # 新会话重载：群与消息都在
    ch2 = Channel(ChatStore(path))
    assert len(ch2.groups()) == 1
    assert ch2.groups()[0].name == "持久群"
    assert ch2.store.count() >= 2
    assert any(m.content == "存下来" for m in ch2.history())


def test_reply_does_not_trigger_more_replies(tmp_path):
    """直接发一条 reply 类型消息，不应产生任何回复。"""
    store = ChatStore(tmp_path / "chat.json")
    ch = Channel(store)
    ch.register(_make_peer("a", "A", tmp_path))
    ch.register(_make_peer("b", "B", tmp_path))
    produced = asyncio.run(ch.send(Message.create("a", "b", "已是回复", kind="reply")))
    assert len(produced) == 1
    assert produced[0].kind == "reply"
