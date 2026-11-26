"""Skill 市场（YoAi 侧，内核零改动）。

本地目录式 + 远程 catalog 式：登记技能包 → 安装到 skills 目录 → 发布已安装技能为包。
远程只支持 http(s) catalog 与 zip 包，带 sha256 校验与安全解压；不自动 pip 安装。
requirements / lockfile 随 catalog 或包写入安装目录。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yoai.skills.store import SkillStore


class SkillMarket:
    def __init__(self, data_dir: str | Path, store: SkillStore) -> None:
        self.root = Path(data_dir) / "skills"
        self.catalog_path = self.root / "market.json"
        self.sources_path = self.root / "market_sources.json"
        self.packages_dir = self.root / "market"
        self.store = store
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._sources: list[str] = []
        self._load_sources()
        self._load()

    def _load(self) -> None:
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        if not self.catalog_path.exists():
            return
        try:
            raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            items = raw.get("skills", []) if isinstance(raw, dict) else []
            self._items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item.setdefault("source_type", "local")
                self._items.append(item)
        except (OSError, ValueError):
            self._items = []

    def _save(self) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"skills": self._items}, ensure_ascii=False, indent=2)
        self.catalog_path.write_text(text, encoding="utf-8")

    def _load_sources(self) -> None:
        if not self.sources_path.exists():
            return
        try:
            raw = json.loads(self.sources_path.read_text(encoding="utf-8"))
            sources = raw.get("sources", []) if isinstance(raw, dict) else []
            self._sources = [str(s) for s in sources
                             if str(s).startswith(("http://", "https://"))]
        except (OSError, ValueError):
            self._sources = []

    def _save_sources(self) -> None:
        self.sources_path.parent.mkdir(parents=True, exist_ok=True)
        self.sources_path.write_text(
            json.dumps({"sources": self._sources}, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(i) for i in self._items]

    def list_sources(self) -> list[str]:
        with self._lock:
            return list(self._sources)

    def add_remote(self, url: str, *, auto_refresh: bool = True) -> list[str]:
        clean = str(url).strip()
        if not clean.startswith(("http://", "https://")):
            raise ValueError("远程市场仅支持 http/https catalog")
        with self._lock:
            if clean not in self._sources:
                self._sources.append(clean)
                self._save_sources()
        if auto_refresh:
            self.refresh_remote()
        return self.list_sources()

    def remove_remote(self, url: str) -> bool:
        with self._lock:
            before = len(self._sources)
            self._sources = [s for s in self._sources if s != str(url).strip()]
            self._save_sources()
            return len(self._sources) < before

    @staticmethod
    def _abs_url(value: str, base: str) -> str:
        value = str(value).strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        return urllib.parse.urljoin(base, value)

    @staticmethod
    def _fetch_bytes(url: str, *, timeout: float = 20.0) -> bytes:
        request = urllib.request.Request(url, headers={"Accept": "application/json, application/zip"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"下载失败：{url}（{exc}）") from exc

    @staticmethod
    def _verify_ed25519(data: bytes, signature_b64: str, public_key_pem: str) -> None:
        openssl = shutil.which("openssl")
        if not openssl:
            raise RuntimeError("catalog 要求签名校验，但本机未找到 openssl")
        try:
            signature = base64.b64decode(signature_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("signature 不是合法 base64") from exc
        with tempfile.TemporaryDirectory(prefix="yoai-skill-verify-") as tmp:
            data_path = Path(tmp) / "package.bin"
            sig_path = Path(tmp) / "package.sig"
            key_path = Path(tmp) / "public.pem"
            data_path.write_bytes(data)
            sig_path.write_bytes(signature)
            key_path.write_text(public_key_pem, encoding="utf-8")
            try:
                completed = subprocess.run(
                    [openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(key_path),
                     "-rawin", "-in", str(data_path), "-sigfile", str(sig_path)],
                    capture_output=True, text=True, timeout=30, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"签名校验失败：{exc}") from exc
        if completed.returncode != 0:
            raise ValueError(f"签名校验失败：{(completed.stderr or '').strip()[:300]}")

    def refresh_remote(self) -> list[dict[str, Any]]:
        merged = [i for i in self._items if i.get("source_type") != "remote"]
        for source in self.list_sources():
            try:
                data = json.loads(self._fetch_bytes(source).decode("utf-8"))
            except (ValueError, RuntimeError) as exc:
                print(f"[skill-market] catalog 读取失败 {source}: {exc}",
                      file=__import__("sys").stderr, flush=True)
                continue
            items = data.get("skills", []) if isinstance(data, dict) else []
            for item in items:
                if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                    continue
                name = str(item["name"]).strip()
                merged.append({
                    "name": name,
                    "version": str(item.get("version", "0.1.0")),
                    "description": str(item.get("description", "")),
                    "source": self._abs_url(str(item.get("url", "")), source),
                    "source_type": "remote",
                    "catalog_url": source,
                    "sha256": str(item.get("sha256", "")),
                    "signature": str(item.get("signature", "")),
                    "public_key": str(item.get("public_key", "")),
                    "public_key_url": self._abs_url(
                        str(item.get("public_key_url", "")), source),
                    "requirements": [str(r) for r in (item.get("requirements") or [])],
                    "lockfile_url": self._abs_url(str(item.get("lockfile_url", "")), source),
                    "lockfile": str(item.get("lockfile", "")),
                    "requirements_exists": bool(item.get("requirements") or item.get("requirements_url")),
                    "lock_exists": bool(item.get("lockfile_url") or item.get("lockfile")),
                })
        with self._lock:
            self._items = merged
            self._save()
        return self.list()

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

    @staticmethod
    def _extract_zip(data: bytes, dest: Path) -> None:
        with zipfile.ZipFile(__import__("io").BytesIO(data)) as archive:
            root = dest.resolve()
            for info in archive.infolist():
                if info.is_dir():
                    continue
                target = (root / info.filename).resolve()
                if target != root and root not in target.parents:
                    raise ValueError(f"压缩包路径越界：{info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))

    def _prepare_remote_package(
        self, entry: dict[str, Any], tmp: tempfile.TemporaryDirectory,
    ) -> Path:
        url = str(entry.get("source", ""))
        if not url.startswith(("http://", "https://")):
            raise ValueError("远程技能包 URL 非法")
        data = self._fetch_bytes(url)
        expected = str(entry.get("sha256", "")).strip().lower()
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("远程技能包 sha256 校验失败")
        signature = str(entry.get("signature", "")).strip()
        if signature:
            public_key = str(entry.get("public_key", "")).strip()
            key_url = str(entry.get("public_key_url", "")).strip()
            if not public_key and key_url:
                public_key = self._fetch_bytes(key_url).decode("utf-8", "replace")
            if not public_key:
                raise ValueError("catalog 提供签名但缺少 public_key")
            self._verify_ed25519(data, signature, public_key)
        dest = Path(tmp.name) / "package"
        dest.mkdir(parents=True, exist_ok=True)
        self._extract_zip(data, dest)
        manifest = dest / "skill.json"
        if not manifest.exists():
            raise ValueError("远程技能包缺少 skill.json")
        requirements = dest / "requirements.txt"
        inline = entry.get("requirements") or []
        if inline and not requirements.exists():
            requirements.write_text("\n".join(str(r) for r in inline) + "\n",
                                    encoding="utf-8")
        lockfile = dest / "requirements.lock.txt"
        lock_text = str(entry.get("lockfile", ""))
        if lock_text and not lockfile.exists():
            lockfile.write_text(lock_text, encoding="utf-8")
        lock_url = str(entry.get("lockfile_url", ""))
        if lock_url and not lockfile.exists():
            lockfile.write_bytes(self._fetch_bytes(lock_url))
        return dest

    @staticmethod
    def _venv_python(venv: Path) -> Path:
        if os.name == "nt":
            return venv / "Scripts" / "python.exe"
        return venv / "bin" / "python"

    def install_dependencies(self, name: str) -> dict[str, Any]:
        """在技能自己的 venv 中安装依赖；失败只记录日志，不破坏技能安装。"""
        target = self.root / name
        requirements = target / ("requirements.lock.txt"
                                 if (target / "requirements.lock.txt").exists()
                                 else "requirements.txt")
        log_path = target / "deps_install.log"
        if not requirements.exists():
            return {"ok": False, "reason": "没有 requirements/lockfile", "log": str(log_path)}
        venv = target / ".venv"
        uv = shutil.which("uv")
        commands: list[list[str]] = []
        if uv:
            commands = [
                [uv, "venv", str(venv)],
                [uv, "pip", "install", "--python", str(self._venv_python(venv)),
                 "-r", str(requirements)],
            ]
        else:
            commands = [
                [sys.executable, "-m", "venv", str(venv)],
                [str(self._venv_python(venv)), "-m", "pip", "install", "-r",
                 str(requirements)],
            ]
        logs: list[str] = []
        try:
            for command in commands:
                completed = subprocess.run(
                    command, cwd=str(target), capture_output=True, text=True,
                    timeout=300, check=False,
                )
                logs.append(f"$ {' '.join(command)}\n{completed.stdout}\n{completed.stderr}")
                if completed.returncode != 0:
                    raise RuntimeError(f"命令失败：{completed.returncode}")
            ok = True
            reason = f"已安装到 {venv}"
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            ok = False
            reason = str(exc)
        log_path.write_text("\n".join(logs), encoding="utf-8")
        return {"ok": ok, "reason": reason, "log": str(log_path),
                "venv": str(venv), "installed": self._venv_python(venv).exists()}

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
            "source_type": "local",
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._items = [i for i in self._items if i.get("name") != name]
            self._items.append(entry)
            self._save()
        return entry

    def _rsi_candidate(self, name: str, manifest: dict[str, Any]) -> str:
        """把技能能力映射成 RSI 候选节点；只入档案、不进路由。"""
        from yoai.evolution import EvolutionArchive, EvolutionReportStore, ExpertSpec
        archive = EvolutionArchive(self.root.parent / "evolution" / "evolution.json")
        root = archive.root or archive.create_root("通用根", ExpertSpec())
        spec = ExpertSpec(
            tools=tuple(str(t) for t in (manifest.get("tools") or [])),
            prompt_suffix=str(manifest.get("prompt", "")),
            capability_tags=(name,),
        )
        node = archive.create_child(
            root.id, f"skill:{name}", spec,
            diff={"dimension": "skill_integration", "skill": name,
                  "source": "market_install", "reason": "技能安装后自动纳入 RSI 候选"},
        )
        reports = EvolutionReportStore(self.root.parent)
        reports.add({
            "id": f"skill-candidate-{node.id}", "evidence_id": "",
            "triggered": True, "cause": "rsi_skill_candidate",
            "new_node_id": node.id,
            "reason": f"技能 {name} 安装后自动创建候选；未进路由、未晋升",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "rsi_skill_candidate", "skill": name,
        })
        return node.id

    def install(self, name: str, *, auto_install_deps: bool = True) -> dict[str, Any]:
        with self._lock:
            entry = next((dict(i) for i in self._items if i.get("name") == name), None)
        if entry is None:
            raise ValueError(f"市场中没有技能：{name}")
        tmp: tempfile.TemporaryDirectory | None = None
        try:
            if entry.get("source_type") == "remote":
                tmp = tempfile.TemporaryDirectory(prefix="yoai-remote-skill-")
                package = self._prepare_remote_package(entry, tmp)
            else:
                package = Path(str(entry.get("source", "")))
            if not package.is_dir():
                raise ValueError("技能包目录不存在")
            manifest = self._read_manifest(package)
            pkg_name = str(manifest["name"]).strip()
            if pkg_name != name:
                raise ValueError(f"包名不一致：{name} != {pkg_name}")

            target = self.root / name
            if target.exists():
                backup = target.with_name(
                    f"{name}.bak-{int(datetime.now(timezone.utc).timestamp())}")
                target.rename(backup)
            shutil.copytree(package, target)

            requirements = target / "requirements.txt"
            if not requirements.exists():
                inline = manifest.get("requirements") or []
                requirements.write_text("\n".join(str(r) for r in inline) + "\n",
                                        encoding="utf-8")
            lockfile = target / "requirements.lock.txt"
            deps = self.install_dependencies(name) if auto_install_deps else None

            self._upsert_skill_manifest(manifest, requirements_exists=True,
                                        lock_exists=lockfile.exists())
            rsi_node = self._rsi_candidate(name, manifest)
            self.store.refresh()
            with self._lock:
                for item in self._items:
                    if item.get("name") == name:
                        item["installed"] = True
                        item["rsi_node_id"] = rsi_node
                        item["installed_at"] = datetime.now(timezone.utc).isoformat()
                        break
                self._save()
            return {"name": name, "target": str(target),
                    "requirements_exists": True, "lock_exists": lockfile.exists(),
                    "deps": deps, "rsi_node_id": rsi_node}
        finally:
            if tmp is not None:
                tmp.cleanup()

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
            "source_type": "local",
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
        items = self.list()
        for item in items:
            item.setdefault("source_type", "local")
        return {"catalog": str(self.catalog_path),
                "sources": self.list_sources(),
                "packages_dir": str(self.packages_dir),
                "items": items}
