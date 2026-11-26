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

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from yai_core.types import ToolSpec

_SAFE_ENV_KEYS = (
    "PATH", "SystemRoot", "TEMP", "TMP", "HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT",
    "ProgramFiles", "ProgramFiles(x86)",
)
_META_TOOLS = {"skill_list", "skill_load", "skill_run", "skill_resource_read", "list_tools"}


def _safe_env() -> dict[str, str]:
    env: dict[str, str] = {}
    lower = {k.lower(): k for k in os.environ}
    for key in _SAFE_ENV_KEYS:
        actual = lower.get(key.lower())
        if actual:
            env[actual] = os.environ[actual]
    return env


class SkillStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "skills" / "skills.json"
        self._lock = threading.RLock()
        self._skills: list[dict[str, Any]] = []
        self._specs: list[ToolSpec] = []
        self._mtime: str | None = None
        self.refresh()

    # --- 配置 ---
    def _mtime_now(self) -> str | None:
        try:
            if not self.path.exists():
                return None
            return hashlib.sha256(self.path.read_bytes()).hexdigest()
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
                    scripts = []
                    for s in item.get("scripts") or []:
                        if isinstance(s, dict) and str(s.get("name", "")).strip():
                            scripts.append({
                                "name": str(s["name"]).strip(),
                                "path": str(s.get("path", "")).strip(),
                                "description": str(s.get("description", "")),
                                "timeout": float(s.get("timeout", 15) or 15),
                            })
                    skills.append({
                        "name": str(item["name"]).strip(),
                        "description": str(item.get("description", "")),
                        "prompt": str(item.get("prompt", "")),
                        "tools": [str(t) for t in (item.get("tools") or [])],
                        "enforce_tools": bool(item.get("enforce_tools", False)),
                        "scripts": scripts,
                        "resources": [str(r) for r in (item.get("resources") or [])],
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
    def _bundle_dir(self, name: str) -> Path:
        return self.path.parent / name

    def _skill(self, name: str) -> dict[str, Any] | None:
        self._ensure_fresh()
        with self._lock:
            return next((dict(s) for s in self._skills if s["name"] == name), None)

    def _build_specs(self, agent: Any = None) -> list[ToolSpec]:
        def skill_list() -> str:
            self._ensure_fresh()
            with self._lock:
                items = [{"name": s["name"], "description": s["description"],
                          "scripts": [x["name"] for x in s["scripts"]],
                          "resources": s["resources"]}
                         for s in self._skills]
            return json.dumps(items, ensure_ascii=False)

        def skill_load(name: str) -> str:
            skill = self._skill(name)
            if skill is None:
                return f"技能不存在：{name}"
            tools = ", ".join(skill["tools"]) or "无"
            scripts = ", ".join(x["name"] for x in skill["scripts"]) or "无"
            resources = ", ".join(skill["resources"]) or "无"
            if agent is not None and skill["enforce_tools"] and hasattr(agent, "set_skill_whitelist"):
                agent.set_skill_whitelist(set(skill["tools"]) | _META_TOOLS)
            return (f"[技能：{skill['name']}]\n{skill['prompt']}\n\n"
                    f"建议工具：{tools}\n脚本包：{scripts}\n资源包：{resources}\n"
                    f"工具仍需按当前权限档位调用。")

        def skill_run(name: str, script: str, args: dict[str, Any] | None = None) -> str:
            skill = self._skill(name)
            if skill is None:
                return f"技能不存在：{name}"
            spec = next((s for s in skill["scripts"] if s["name"] == script), None)
            if spec is None:
                return f"技能 {name} 没有脚本 {script}"
            bundle = self._bundle_dir(name)
            target = (bundle / spec["path"]).resolve()
            if not target.is_file() or bundle.resolve() not in target.parents:
                return f"脚本路径非法：{spec['path']}"
            try:
                completed = subprocess.run(
                    [sys.executable, str(target)], input=json.dumps(args or {}, ensure_ascii=False),
                    capture_output=True, text=True, timeout=spec["timeout"],
                    cwd=str(bundle), env=_safe_env(), check=False,
                )
            except subprocess.TimeoutExpired:
                return f"脚本 {script} 超时（>{spec['timeout']}s）"
            except OSError as exc:
                return f"脚本 {script} 启动失败：{exc}"
            if completed.returncode != 0:
                return f"脚本 {script} 失败：{completed.stderr.strip()[:500]}"
            out = completed.stdout.strip()
            try:
                return json.dumps(json.loads(out), ensure_ascii=False) if out else ""
            except ValueError:
                return out[:20000]

        def skill_resource_read(name: str, path: str) -> str:
            skill = self._skill(name)
            if skill is None:
                return f"技能不存在：{name}"
            if path not in skill["resources"]:
                return f"资源未声明：{path}"
            bundle = self._bundle_dir(name).resolve()
            target = (bundle / path).resolve()
            if not target.is_file() or bundle not in target.parents:
                return f"资源路径非法：{path}"
            try:
                return target.read_text(encoding="utf-8", errors="replace")[:200000]
            except OSError as exc:
                return f"读取资源失败：{exc}"

        return [
            ToolSpec(name="skill_list", description="列出当前可用的技能包。",
                     input_schema={"type": "object", "properties": {}},
                     handler=skill_list, source="native", version="v1"),
            ToolSpec(name="skill_load", description="按需加载一个技能的提示词、脚本包与资源包。",
                     input_schema={"type": "object", "properties": {
                         "name": {"type": "string", "description": "技能名称"}},
                         "required": ["name"]},
                     handler=skill_load, source="native", version="v1"),
            ToolSpec(name="skill_run", description="运行技能脚本包中的一个脚本。",
                     input_schema={"type": "object", "properties": {
                         "name": {"type": "string"}, "script": {"type": "string"},
                         "args": {"type": "object"}},
                         "required": ["name", "script"]},
                     handler=skill_run, source="native", version="v1"),
            ToolSpec(name="skill_resource_read", description="读取技能资源包中声明的文本文件。",
                     input_schema={"type": "object", "properties": {
                         "name": {"type": "string"}, "path": {"type": "string"}},
                         "required": ["name", "path"]},
                     handler=skill_resource_read, source="native", version="v1"),
        ]

    def tool_specs(self, agent: Any = None) -> list[ToolSpec]:
        self._ensure_fresh()
        if agent is not None:
            return self._build_specs(agent)
        with self._lock:
            return list(self._specs)

    def status(self) -> dict[str, Any]:
        self._ensure_fresh()
        with self._lock:
            return {"config": str(self.path),
                    "skills": [dict(s) for s in self._skills],
                    "tools": [spec.name for spec in self._specs]}
