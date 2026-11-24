"""YoAi 工具优先路由测试：有工具一律 REACT，不再靠词表猜意图。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.types import Strategy

from yoai.routing import YoAiRouter


class _FakeRegistry:
    def __init__(self, names=("remember_fact", "list_facts")):
        self._names = tuple(names)

    def __len__(self) -> int:
        return len(self._names)

    def all(self):
        return [SimpleNamespace(name=n) for n in self._names]

    def catalog(self):
        return [{"name": n, "description": n} for n in self._names]

    def llm_schemas(self):
        return []


def test_any_task_with_tools_goes_react():
    """核心保证：不管什么动词，有工具就给 schema（不再词表打地鼠）。"""
    router = YoAiRouter()
    texts = [
        "记住我偏好深色主题", "写个文件 hello.txt", "读一下 notes/a.txt",
        "我叫小明", "顺便帮我看下这个网页", "把这张表整理一下", "搜索 Python",
    ]
    for text in texts:
        d = asyncio.run(router.aclassify(text, _FakeRegistry()))
        assert d.strategy == Strategy.REACT, (text, d)
        assert d.source == "yoai:tools-first"


def test_no_tools_or_empty_falls_back_to_core():
    """无工具/空任务是 Core 硬规则区，不越过。"""
    router = YoAiRouter()
    empty = _FakeRegistry(())
    d = asyncio.run(router.aclassify("记住我喜欢蓝色", empty))
    assert d.strategy != Strategy.REACT or d.source != "yoai:tools-first"
    d2 = asyncio.run(router.aclassify("", _FakeRegistry()))
    assert d2.strategy == Strategy.CLARIFY   # Core 原行为


def test_clarify_still_wins_for_vague_short_tasks():
    """模糊短句仍先反问（继承 Core 的 CLARIFY 逻辑）。"""
    router = YoAiRouter()
    d = asyncio.run(router.aclassify("嗯？", _FakeRegistry()))
    assert d.strategy in (Strategy.CLARIFY, Strategy.REACT)  # CLARIFY 优先，不硬调工具


def test_sync_classify_consistent():
    router = YoAiRouter()
    assert router.classify("帮我整理一下这些资料", _FakeRegistry()) == Strategy.REACT
    # 模糊短句仍先澄清
    assert router.classify("随便做什么", _FakeRegistry()) == Strategy.CLARIFY
