"""2026-11-24 YoAi 自检反馈落地的五项工具能力测试。

- now：真实时间源（事件时间戳/排序的前提）；
- forget_fact / forget_event / recent_events：记忆层删除能力（只有写没有删的补齐）；
- list_tools：模型自省能力边界；
- request_capability：Core 现成 meta 工具接线（常驻工具表）；
- file_ro_list / file_ro_read：只读挂载扩展目录（调试宿主项目用，白名单外拒绝）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.temporal_memory import TemporalMemory  # noqa: E402
from yoai.tools_builtin import readonly_tool_specs  # noqa: E402


# --- now ---

def test_now_returns_iso_with_offset(tmp_path):
    agent = YoAiAgent(data_dir=tmp_path / "d")
    value = agent.capabilities.now()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None   # 带时区，可做跨时区排序
    # 与真实时钟差距小于 5 秒（模型不用再猜时间）
    assert abs((datetime.now().astimezone() - parsed).total_seconds()) < 5


# --- forget / recent_events ---

def test_temporal_memory_forget_exact_match(tmp_path):
    tmem = TemporalMemory(tmp_path / "tmem.json")
    tmem.remember_event("用户偏好深色主题", tag="pref", _source="fallback")
    tmem.remember_event("用户偏好深色主题", tag="pref", _source="fallback")  # 重复键场景
    tmem.remember_event("用户喜欢咖啡", tag="pref", _source="fallback")
    assert tmem.forget("用户偏好深色主题", tag="pref") == 2   # 重复的两条都删
    assert tmem.forget("不存在的内容") == 0                    # 无匹配如实返回 0
    assert [e["what"] for e in tmem.facts_by_tag("pref")] == ["用户喜欢咖啡"]


def test_forget_event_and_recent_events(tmp_path):
    agent = YoAiAgent(data_dir=tmp_path / "d")
    agent.capabilities.remember_event("第一条记录")
    agent.capabilities.remember_event("第二条记录")
    recent = agent.capabilities.recent_events(2)
    assert [e["what"] for e in recent] == ["第二条记录", "第一条记录"]   # 新的在前
    # 删除用查到的原文，成功；凭记忆改写的原文删不到并如实说明
    assert "已删除 1 条" in agent.capabilities.forget_event("第二条记录")
    assert "没有精确匹配" in agent.capabilities.forget_event("第二条记录 (改写过的)")


def test_forget_fact_kv(tmp_path):
    agent = YoAiAgent(data_dir=tmp_path / "d")
    agent.capabilities.remember_fact("主题偏好", "深色主题")
    assert agent.capabilities.forget_fact("主题偏好").startswith("已删除")
    assert agent.capabilities.recall_fact("主题偏好") == "未找到"
    assert "没有名为" in agent.capabilities.forget_fact("主题偏好")


# --- list_tools / request_capability 常驻 ---

def test_list_tools_and_request_capability_registered(tmp_path):
    agent = YoAiAgent(data_dir=tmp_path / "d", builtin_tools=True)
    names = {s.name for s in agent._all_tool_specs}
    assert "list_tools" in names
    assert "request_capability" in names
    # list_tools 运行时如实列出全部（含它自己和 request_capability）
    raw = agent.core.registry.run("list_tools", {}) if hasattr(
        agent.core.registry, "run") else None
    if raw is None:   # registry 执行入口名不同则直接调 handler
        spec = next(s for s in agent._all_tool_specs if s.name == "list_tools")
        raw = spec.handler()
    data = json.loads(raw)
    listed = {item["name"] for item in data}
    assert {"list_tools", "request_capability", "remember_fact"} <= listed
    assert all(item["description"] for item in data)   # 每个工具带描述


# --- 只读挂载 ---

def test_readonly_specs_empty_roots_noop():
    assert readonly_tool_specs([]) == []
    assert readonly_tool_specs([ROOT / "definitely_not_exists_xyz"]) == []


def test_readonly_read_and_list(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.py").write_text("print('hello')", encoding="utf-8")
    specs = {s.name: s for s in readonly_tool_specs([tmp_path])}
    assert set(specs) == {"file_ro_list", "file_ro_read"}
    assert json.loads(specs["file_ro_list"].handler("")) == {
        str(tmp_path): ["src/"],
    }
    assert "demo.py/" in json.loads(specs["file_ro_list"].handler("src"))[0] or \
        json.loads(specs["file_ro_list"].handler("src")) == ["demo.py"]
    assert specs["file_ro_read"].handler("src/demo.py") == "print('hello')"


def test_readonly_rejects_outside_roots(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    (tmp_path / "inner").mkdir()   # 白名单根必须在挂载前存在，否则被过滤
    (tmp_path / "inner" / "ok.txt").write_text("ok", encoding="utf-8")
    specs = {s.name: s for s in readonly_tool_specs([tmp_path / "inner"])}

    def _expect_permission_error(fn):
        try:
            fn()
        except PermissionError:
            return True
        except Exception:  # noqa: BLE001
            return False
        return False

    assert _expect_permission_error(lambda: specs["file_ro_read"].handler(str(outside / "secret.txt")))
    # 白名单内的正常读
    assert specs["file_ro_read"].handler(str(tmp_path / "inner" / "ok.txt")) == "ok"


def test_agent_wires_readonly_roots(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "README.md").write_text("# proj", encoding="utf-8")
    agent = YoAiAgent(data_dir=tmp_path / "d", builtin_tools=True,
                      readonly_roots=[project])
    names = {s.name for s in agent._all_tool_specs}
    assert {"file_ro_read", "file_ro_list"} <= names
