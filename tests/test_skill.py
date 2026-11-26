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
    assert set(specs) == {"skill_list", "skill_load"}
    assert "research" in specs["skill_list"].handler()
    loaded = specs["skill_load"].handler(name="research")
    assert "先列主题" in loaded and "web_search" in loaded


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
