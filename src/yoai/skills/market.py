"""Skill 本地市场（YoAi 侧，内核零改动）。

市场是本地目录式：登记本地技能包 → 安装到 skills 目录 → 发布已安装技能为包。
不做远端下载、不自动 pip 安装；requirements/lockfile 随包复制与校验。
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yoai.skills.store import SkillStore


class SkillMarket:
    def __init__(self, data_dir: str | Path, store: SkillStore) -> None:
        self.root = Path(data_dir) / "skills"
        self.catalog_path = self.root / "market.json"
        self.packages_dir = self.root / "market"
        self.store = store
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        if not self.catalog_path.exists():
            return
        try:
            raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            items = raw.get("skills", []) if isinstance(raw, dict) else []
            self._items = [i for i in items if isinstance(i, dict)]
        except (OSError, ValueError):
            self._items = []

    def _save(self) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"skills": self._items}, ensure_ascii=False, indent=2)
        self.catalog_path.write_text(text, encoding="utf-8")

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(i) for i in self._items]

    @staticmethod
    def _read_manifest(package: Path) -> dict[str, Any]:
        manifest = package / "skill.json"
        if not manifest.is_file():
            raise ValueError(f"技能包缺少 skill.json：{package}")
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"skill.json 解析失败：{exc}") from exc
        if not isinstance(data, dict) or not str(data.get("name", "")).strip():
            raise ValueError("skill.json 必须包含 name")
        return data

    def add_local(self, source: str | Path) -> dict[str, Any]:
        package = Path(source).expanduser().resolve()
        if not package.is_dir():
            raise ValueError("本地技能包目录不存在")
        manifest = self._read_manifest(package)
        name = str(manifest["name"]).strip()
        entry = {
            "name": name,
            "version": str(manifest.get("version", "0.1.0")),
            "description": str(manifest.get("description", "")),
            "source": str(package),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._items = [i for i in self._items if i.get("name") != name]
            self._items.append(entry)
            self._save()
        return entry

    def install(self, name: str) -> dict[str, Any]:
        with self._lock:
            entry = next((dict(i) for i in self._items if i.get("name") == name), None)
        if entry is None:
            raise ValueError(f"市场中没有技能：{name}")
        package = Path(str(entry.get("source", "")))
        manifest = self._read_manifest(package)
        pkg_name = str(manifest["name"]).strip()
        if pkg_name != name:
            raise ValueError(f"包名不一致：{name} != {pkg_name}")

        target = self.root / name
        if target.exists():
            backup = target.with_name(f"{name}.bak-{int(datetime.now(timezone.utc).timestamp())}")
            target.rename(backup)
        shutil.copytree(package, target)

        requirements = target / "requirements.txt"
        if not requirements.exists():
            inline = manifest.get("requirements") or []
            requirements.write_text("\n".join(str(r) for r in inline) + "\n",
                                    encoding="utf-8")
        lockfile = target / "requirements.lock.txt"

        self._upsert_skill_manifest(manifest, requirements_exists=True,
                                    lock_exists=lockfile.exists())
        self.store.refresh()
        with self._lock:
            for item in self._items:
                if item.get("name") == name:
                    item["installed"] = True
                    item["installed_at"] = datetime.now(timezone.utc).isoformat()
                    break
            self._save()
        return {"name": name, "target": str(target),
                "requirements_exists": True, "lock_exists": lockfile.exists()}

    def publish(self, name: str) -> dict[str, Any]:
        installed = self.root / name
        if not installed.is_dir():
            raise ValueError(f"技能未安装：{name}")
        manifest = self.store.status().get("skills", [])
        item = next((s for s in manifest if s.get("name") == name), None)
        if item is None:
            raise ValueError(f"技能清单中没有：{name}")

        package = self.packages_dir / name
        if package.exists():
            backup = package.with_name(f"{name}.bak-{int(datetime.now(timezone.utc).timestamp())}")
            package.rename(backup)
        shutil.copytree(installed, package,
                        ignore=shutil.ignore_patterns(".venv", "__pycache__"))

        payload = {
            "name": name,
            "version": "0.1.0",
            "description": item.get("description", ""),
            "prompt": item.get("prompt", ""),
            "tools": item.get("tools", []),
            "enforce_tools": item.get("enforce_tools", False),
            "scripts": item.get("scripts", []),
            "resources": item.get("resources", []),
            "requirements": item.get("requirements", []),
        }
        (package / "skill.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        requirements = package / "requirements.txt"
        if not requirements.exists():
            requirements.write_text("\n".join(payload["requirements"]) + "\n",
                                    encoding="utf-8")
        lockfile = package / "requirements.lock.txt"

        entry = {
            "name": name, "version": payload["version"],
            "description": payload["description"], "source": str(package),
            "published_at": datetime.now(timezone.utc).isoformat(),
            "requirements_exists": requirements.exists(),
            "lock_exists": lockfile.exists(),
        }
        with self._lock:
            self._items = [i for i in self._items if i.get("name") != name]
            self._items.append(entry)
            self._save()
        return entry

    def remove(self, name: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i.get("name") != name]
            self._save()
            return len(self._items) < before

    def _upsert_skill_manifest(self, manifest: dict[str, Any], *,
                               requirements_exists: bool, lock_exists: bool) -> None:
        path = self.root / "skills.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"skills": []}
        except (OSError, ValueError):
            data = {"skills": []}
        skills = data.get("skills", []) if isinstance(data, dict) else []
        skills = [s for s in skills if not (isinstance(s, dict) and s.get("name") == manifest["name"])]
        skills.append({
            "name": manifest["name"],
            "description": manifest.get("description", ""),
            "prompt": manifest.get("prompt", ""),
            "tools": manifest.get("tools", []),
            "enforce_tools": manifest.get("enforce_tools", False),
            "scripts": manifest.get("scripts", []),
            "resources": manifest.get("resources", []),
            "requirements": manifest.get("requirements", []),
            "requirements_file": "requirements.txt" if requirements_exists else "",
            "enabled": True,
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"skills": skills}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def status(self) -> dict[str, Any]:
        return {"catalog": str(self.catalog_path),
                "packages_dir": str(self.packages_dir),
                "items": self.list()}
