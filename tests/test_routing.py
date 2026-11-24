"""YoAi 侧路由扩展测试：记忆写入意图必须走 REACT（拿到工具 schema）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.types import Strategy

from yoai.routing import MemoryIntentSelector


class _FakeRegistry:
    def __len__(self) -> int:
        return 12


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
        assert s.source == "yoai:memory-intent"


def test_non_memory_tasks_abstain():
    """非记忆任务不表态，交回 Core 规则（保持原路由行为）。"""
    sel = MemoryIntentSelector()
    for text in [
        "你好",
        "帮我写首诗",
        "今天天气怎么样",
        "列出我记住的所有事情",   # Core 规则已能识别"列出"
    ]:
        assert sel.suggest(text, _FakeRegistry()) is None, text


def test_hard_rule_zones_respected():
    """空任务/无工具是 Core 硬规则区，扩展不越过。"""
    sel = MemoryIntentSelector()
    assert sel.suggest("", _FakeRegistry()) is None
    assert sel.suggest("记住我喜欢蓝色", object()) is None  # 无 __len__


def test_record_is_noop():
    sel = MemoryIntentSelector()
    assert sel.record("记住X", _FakeRegistry(), Strategy.REACT, {}) is None
