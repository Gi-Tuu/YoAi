"""专家工具白名单接线测试：白名单生效 + 向后兼容。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:/Competition/YAI Agent Core") / "src"))

from yoai.agent import YoAiAgent  # noqa: E402
from yai_core import ScriptedModel, ModelResponse  # noqa: E402


def test_no_filter_keeps_all_tools(tmp_path: Path):
    """不启用 tool_filter 时工具集完整（向后兼容）。"""
    a = YoAiAgent(model=ScriptedModel([ModelResponse(content="ok")]), data_dir=tmp_path / "a")
    tools = set(a.list_tools())
    assert "remember_fact" in tools and "list_facts" in tools
    assert len(tools) > 5


def test_whitelist_filters_tools(tmp_path: Path):
    """启用 tool_filter 后只剩白名单工具。"""
    a = YoAiAgent(
        model=ScriptedModel([ModelResponse(content="ok")]), data_dir=tmp_path / "b",
        tool_filter=lambda task: {"list_facts"},
    )
    a._apply_tool_filter("随便一个问题")
    assert a.list_tools() == ["list_facts"]


def test_whitelist_none_means_all(tmp_path: Path):
    """filter 返回 None 表示不限制。"""
    a = YoAiAgent(
        model=ScriptedModel([ModelResponse(content="ok")]), data_dir=tmp_path / "c",
        tool_filter=lambda task: None,
    )
    before = set(a.list_tools())
    a._apply_tool_filter("问题")
    assert set(a.list_tools()) == before


def test_filter_changes_between_tasks(tmp_path: Path):
    """不同任务可切不同白名单（路由后专家工具不同）。"""
    a = YoAiAgent(
        model=ScriptedModel([ModelResponse(content="ok")]), data_dir=tmp_path / "d",
        tool_filter=lambda task: {"list_facts"} if "A" in task else {"remember_fact"},
    )
    a._apply_tool_filter("任务A")
    assert a.list_tools() == ["list_facts"]
    a._apply_tool_filter("任务B")
    assert a.list_tools() == ["remember_fact"]


def test_filter_keeps_loop_reference(tmp_path: Path):
    """就地过滤后，core 与 loop 仍共享同一 registry 对象。"""
    a = YoAiAgent(
        model=ScriptedModel([ModelResponse(content="ok")]), data_dir=tmp_path / "e",
        tool_filter=lambda task: {"list_facts"},
    )
    reg_before = id(a.core.registry)
    a._apply_tool_filter("任务A")
    assert id(a.core.registry) == reg_before
    # loop 持有的引用也应是同一对象
    loop = a.core._loop
    assert loop.registry is a.core.registry
    assert [s.name for s in loop.registry.all()] == ["list_facts"]
