"""Skill 基础层守护测试：配置、热更新、技能加载工具。"""

from __future__ import annotations

import json

import pytest

from yoai.skills import SkillStore


def _config(tmp_path, skills):
    path = tmp_path / "skills" / "skills.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"skills": skills}, ensure_ascii=False), encoding="utf-8")
    return path


def test_skill_store_loads_and_registers_tools(tmp_path):
    _config(tmp_path, [{
        "name": "research", "description": "调研流程",
        "prompt": "先列主题，再逐条汇总。", "tools": ["web_search", "web_fetch"],
    }])
    store = SkillStore(tmp_path)
    assert [s["name"] for s in store.status()["skills"]] == ["research"]
    specs = {s.name: s for s in store.tool_specs()}
    assert set(specs) == {"skill_list", "skill_load", "skill_run", "skill_resource_read"}
    assert "research" in specs["skill_list"].handler()
    loaded = specs["skill_load"].handler(name="research")
    assert "先列主题" in loaded and "web_search" in loaded


def test_skill_script_and_resource_packs(tmp_path):
    bundle = tmp_path / "skills" / "demo"
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    (bundle / "templates").mkdir(parents=True, exist_ok=True)
    (bundle / "scripts" / "upper.py").write_text(
        "import json,sys\nargs=json.loads(sys.stdin.read())\n"
        "print(json.dumps({'text': str(args.get('text','')).upper()}))\n",
        encoding="utf-8")
    (bundle / "templates" / "report.md").write_text("# 报告模板\n", encoding="utf-8")
    _config(tmp_path, [{
        "name": "demo", "prompt": "演示", "tools": ["web_search"],
        "scripts": [{"name": "upper", "path": "scripts/upper.py"}],
        "resources": ["templates/report.md"],
    }])
    specs = {s.name: s for s in SkillStore(tmp_path).tool_specs()}
    result = specs["skill_run"].handler(name="demo", script="upper", args={"text": "hi"})
    assert json.loads(result)["text"] == "HI"
    assert specs["skill_resource_read"].handler(
        name="demo", path="templates/report.md").startswith("# 报告模板")
    assert "资源未声明" in specs["skill_resource_read"].handler(
        name="demo", path="../secret.txt")


def test_skill_enforced_whitelist_applies_to_agent(tmp_path):
    from types import SimpleNamespace
    from yoai.agent import YoAiAgent
    from yoai.demo_model import DemoModel

    _config(tmp_path, [{
        "name": "locked", "prompt": "限定工具", "tools": ["web_search"],
        "enforce_tools": True,
    }])
    store = SkillStore(tmp_path)
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "agent",
                      temporal_memory=False, skill_store=store)
    load = next(s for s in agent._all_tool_specs if s.name == "skill_load")
    load.handler(name="locked")
    assert "web_search" in agent._skill_whitelist
    assert "skill_run" in agent._skill_whitelist
    assert "list_tools" in agent._skill_whitelist


def test_skill_store_hot_reload_and_validation(tmp_path):
    path = _config(tmp_path, [])
    store = SkillStore(tmp_path)
    assert store.status()["skills"] == []

    store.set_config(json.dumps({"skills": [{
        "name": "new", "prompt": "提示", "enabled": True,
    }]}, ensure_ascii=False))
    assert [s["name"] for s in store.status()["skills"]] == ["new"]

    path.write_text(json.dumps({"skills": [{"name": "external"}]}), encoding="utf-8")
    assert [s["name"] for s in store.status()["skills"]] == ["external"]

    with pytest.raises(ValueError):
        store.set_config('{"skills": [{}]}')
