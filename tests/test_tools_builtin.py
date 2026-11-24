"""YoAi 内置实操工具测试：文件读写白名单 + 联网。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.tools.registry import ToolRegistry

from yoai.agent import YoAiAgent
from yoai.demo_model import DemoModel
from yoai.tools_builtin import builtin_tool_specs


def _executor(tmp_path: Path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "data",
                      temporal_memory=False, builtin_tools=True)
    return agent, agent.core.executor


def test_tool_registration(tmp_path):
    off = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "off", temporal_memory=False)
    on = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "on",
                   temporal_memory=False, builtin_tools=True)
    added = set(on.list_tools()) - set(off.list_tools())
    assert {"file_list", "file_read", "file_create", "file_patch",
            "web_search", "web_fetch"}.issubset(added)
    # off = 12 原有能力 + 4 新增（now/forget_fact/recent_events/forget_event，
    # 2026-11-24）+ 2 常驻 meta（list_tools/request_capability）
    assert len(off.list_tools()) == 18


def test_file_write_read_and_gate(tmp_path):
    # 用独立 root，避免测试污染真实 workspace（Core 电池是成功即写盘）
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "data2",
                      temporal_memory=False, builtin_tools=False)
    from yoai.tools_builtin import builtin_tool_specs as _specs
    agent.core.register_tools(_specs(tmp_path / "ws"))
    ex = agent.core.executor

    async def run():
        _, ok, out = await ex.execute("file_create", {
            "path": "notes/hello.txt", "content": "你好 YoAi"})
        assert ok, out
        _, ok, out = await ex.execute("file_read", {"path": "notes/hello.txt"})
        assert ok and "你好 YoAi" in out, out
        # 越界写必须被 gate 拒绝
        _, ok, out = await ex.execute("file_create", {
            "path": "outside.txt", "content": "不该成功"})
        assert not ok and "不在允许的写作用域" in out, out
    asyncio.run(run())
    agent.core.shutdown() if hasattr(agent.core, "shutdown") else None


def test_specs_have_gate_for_writes():
    specs = {s.name: s for s in builtin_tool_specs()}
    assert specs["file_create"].governance.gate is not None
    assert specs["file_patch"].governance.gate is not None
    # 读工具不额外挂 gate（root + 符号链接防护由 filesystem 电池自身保证）
    assert specs["file_read"].governance.gate is None


def test_web_tools_real(tmp_path):
    """真实联网测试：两个工具都返回内容。"""
    agent, ex = _executor(tmp_path)

    async def run():
        _, ok, out = await ex.execute("web_search", {"q": "Python", "size": 2})
        assert ok and "results" in out, out[:200]
        _, ok, out = await ex.execute("web_fetch", {"url": "https://example.com"})
        assert ok and "Example Domain" in out, out[:200]
    asyncio.run(run())
