"""YoAi 侧路由扩展测试：记忆/文件意图必须走 REACT（拿到工具 schema）。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.types import Strategy

from yoai.routing import MemoryIntentSelector


class _FakeRegistry:
    def __init__(self, names=("remember_fact", "list_facts")):
        self._names = tuple(names)

    def __len__(self) -> int:
        return len(self._names)

    def all(self):
        return [SimpleNamespace(name=n) for n in self._names]


_FILE_REG = _FakeRegistry(("remember_fact", "file_read", "file_create", "web_search"))


def test_memory_write_intents_route_to_react():
    sel = MemoryIntentSelector()
    for text in [
        "记住我偏好深色主题",
        "记一下我叫小明",
        "请记住我有三个姐妹",
        "我喜欢蓝色",
        "我叫小明",
        "我的生日是5月1日",
    ]:
        s = sel.suggest(text, _FakeRegistry())
        assert s is not None, text
        assert s.strategy == Strategy.REACT, (text, s)
        assert s.source == "yoai:builtin-intent"


def test_file_intents_route_to_react_only_with_file_tools():
    sel = MemoryIntentSelector()
    for text in ["写一个文件 hello.txt", "读一下 notes/a.txt", "把内容保存到文件"]:
        assert sel.suggest(text, _FILE_REG) is not None, text
        # 没装文件工具时不接管（交回 Core 规则）
        assert sel.suggest(text, _FakeRegistry()) is None, text


def test_non_memory_tasks_abstain():
    sel = MemoryIntentSelector()
    for text in ["你好", "帮我写首诗", "今天天气怎么样", "列出我记住的所有事情"]:
        assert sel.suggest(text, _FakeRegistry()) is None, text


def test_hard_rule_zones_respected():
    sel = MemoryIntentSelector()
    assert sel.suggest("", _FakeRegistry()) is None
    assert sel.suggest("记住我喜欢蓝色", object()) is None  # 无 all() 容错


def test_record_is_noop():
    sel = MemoryIntentSelector()
    assert sel.record("记住X", _FakeRegistry(), Strategy.REACT, {}) is None
