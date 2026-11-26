"""Skill 基础层：配置化技能包（YoAi 侧，Core 零改动）。

配置：<data_dir>/skills/skills.json
{
  "skills": [
    {"name": "research", "description": "调研流程", "prompt": "先列主题再汇总…",
     "tools": ["web_search", "web_fetch"], "enabled": true}
  ]
}

技能不是代码包；第一阶段只做「可发现 + 按需加载提示词/建议工具」，
不自动授权工具、不改权限档位。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from yai_core.types import ToolSpec


class SkillStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "skills" / "skills.json"
        self._lock = threading.RLock()
        self._skills: list[dict[str, Any]] = []
        self._specs: list[ToolSpec] = []
        self._mtime: float | None = None
        self.refresh()

    # --- 配置 ---
    def _mtime_now(self) -> float | None:
        try:
            return self.path.stat().st_mtime if self.path.exists() else None
        except OSError:
            return None

    def config_text(self) -> str:
        if not self.path.exists():
            return json.dumps({"skills": []}, ensure_ascii=False, indent=2)
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return json.dumps({"skills": []}, ensure_ascii=False, indent=2)

    def set_config(self, text: str) -> None:
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("skills", []), list):
            raise ValueError("配置需为含 skills 数组的对象")
        for item in parsed.get("skills", []):
            if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                raise ValueError("每个 skill 必须有 name")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")
        self.refresh()

    def refresh(self) -> None:
        skills: list[dict[str, Any]] = []
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for item in raw.get("skills", []) if isinstance(raw, dict) else []:
                    if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                        continue
                    if item.get("enabled", True) is False:
                        continue
                    skills.append({
                        "name": str(item["name"]).strip(),
                        "description": str(item.get("description", "")),
                        "prompt": str(item.get("prompt", "")),
                        "tools": [str(t) for t in (item.get("tools") or [])],
                    })
            except (OSError, ValueError):
                skills = []
        with self._lock:
            self._skills = skills
            self._specs = self._build_specs()
            self._mtime = self._mtime_now()

    def _ensure_fresh(self) -> None:
        if self._mtime != self._mtime_now():
            self.refresh()

    # --- 工具 ---
    def _build_specs(self) -> list[ToolSpec]:
        def skill_list() -> str:
            self._ensure_fresh()
            with self._lock:
                items = [{"name": s["name"], "description": s["description"]}
                         for s in self._skills]
            return json.dumps(items, ensure_ascii=False)

        def skill_load(name: str) -> str:
            self._ensure_fresh()
            with self._lock:
                skill = next((s for s in self._skills if s["name"] == name), None)
            if skill is None:
                return f"技能不存在：{name}"
            tools = ", ".join(skill["tools"]) or "无"
            return (f"[技能：{skill['name']}]\n{skill['prompt']}\n\n"
                    f"建议工具：{tools}\n工具仍需按当前权限档位调用。")

        list_spec = ToolSpec(
            name="skill_list", description="列出当前可用的技能包。",
            input_schema={"type": "object", "properties": {}},
            handler=skill_list, source="native", version="v1",
        )
        load_spec = ToolSpec(
            name="skill_load", description="按需加载一个技能的提示词与建议工具。",
            input_schema={"type": "object", "properties": {
                "name": {"type": "string", "description": "技能名称"}},
                "required": ["name"]},
            handler=skill_load, source="native", version="v1",
        )
        return [list_spec, load_spec]

    def tool_specs(self) -> list[ToolSpec]:
        self._ensure_fresh()
        with self._lock:
            return list(self._specs)

    def status(self) -> dict[str, Any]:
        self._ensure_fresh()
        with self._lock:
            return {"config": str(self.path),
                    "skills": [dict(s) for s in self._skills],
                    "tools": [spec.name for spec in self._specs]}
