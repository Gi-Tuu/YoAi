"""Skill 本地市场守护测试：登记、安装、发布、移除。"""

from __future__ import annotations

import json
from pathlib import Path

from yoai.skills import SkillMarket, SkillStore


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "source-pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "skill.json").write_text(json.dumps({
        "name": "demo", "description": "演示", "prompt": "提示词",
        "tools": ["web_search"], "requirements": ["requests==2.31.0"],
        "scripts": [], "resources": [],
    }, ensure_ascii=False), encoding="utf-8")
    return package


def test_market_add_install_publish_remove(tmp_path):
    store = SkillStore(tmp_path)
    market = SkillMarket(tmp_path, store)
    package = _package(tmp_path)

    entry = market.add_local(package)
    assert entry["name"] == "demo"
    assert market.list()[0]["source"] == str(package.resolve())

    installed = market.install("demo")
    assert Path(installed["target"]).is_dir()
    assert (tmp_path / "skills" / "demo" / "requirements.txt").exists()
    assert any(s["name"] == "demo" for s in store.status()["skills"])
    assert market.list()[0]["installed"] is True

    published = market.publish("demo")
    assert Path(published["source"]).is_dir()
    assert (Path(published["source"]) / "skill.json").exists()
    assert any(i["name"] == "demo" for i in market.list())

    assert market.remove("demo") is True
    assert market.list() == []
