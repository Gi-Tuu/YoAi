"""撤回/编辑覆盖层守护测试：软删除不物理改写 Core 历史。"""

from __future__ import annotations

from types import SimpleNamespace

from yoai.conversation_actions import ConversationActions, ConversationMemory, content_hash


class FakeStore:
    def __init__(self, messages):
        self.messages = list(messages)

    def history(self):
        return list(self.messages)

    async def append_history(self, message):
        self.messages.append(message)

    async def put(self, key, value, ttl_seconds=None):
        pass

    async def get(self, key):
        return None

    async def clear(self):
        self.messages.clear()


def test_hidden_ranges_filter_memory_but_keep_raw(tmp_path):
    actions = ConversationActions(tmp_path)
    store = FakeStore([
        SimpleNamespace(role="user", content="旧问题"),
        SimpleNamespace(role="assistant", content="旧回答"),
        SimpleNamespace(role="user", content="新问题"),
        SimpleNamespace(role="assistant", content="新回答"),
    ])
    memory = ConversationMemory(store, actions, "s1")

    assert len(memory.history()) == 4
    actions.add(session_id="s1", kind="retract", hide_from=0, hide_until=2,
                text_hash=content_hash("旧问题"))
    assert [m.content for m in memory.history()] == ["新问题", "新回答"]
    assert len(store.history()) == 4          # 原始历史仍在，可审计
    assert len(actions.list("s1")) == 1

    # 只作用于本会话
    other = ConversationMemory(store, actions, "s2")
    assert len(other.history()) == 4


def test_corrupt_action_log_is_not_fatal(tmp_path):
    (tmp_path / "conversation_actions.jsonl").write_text("坏行\n", encoding="utf-8")
    actions = ConversationActions(tmp_path)
    assert actions.list("s1") == []
