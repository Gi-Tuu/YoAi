"""项目（一等公民）：绑定宿主机文件夹，会话归属项目，文件读写限制在项目根内。

设计（2026-11-25 所有者拍板）：
- 聊天模式（默认）：无项目，留在沙箱，不发放写能力，记忆全局共享。
- 项目模式：绑定宿主机文件夹，挂载 proj_* 读写工具，记忆按项目隔离。
- 项目写工具的审批由权限档位决定：full 免审批；smart/manual 走 Core 审批通道。
内核零改动——项目是 YoAi 侧的数据与工具扩展。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Project:
    id: str
    name: str
    path: str            # 宿主机文件夹绝对路径（resolve 后）
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        return cls(
            id=str(d.get("id", "")), name=str(d.get("name", "")),
            path=str(d.get("path", "")), created_at=str(d.get("created_at", "")),
        )


class ProjectError(ValueError):
    """项目操作失败（路径非法/不存在/重名等）——面向用户的可读错误。"""


class ProjectStore:
    """项目 CRUD，持久化 <data_dir>/projects.json。纯数据，不碰 agent。"""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._index = self.data_dir / "projects.json"
        self._projects: dict[str, Project] = {}
        self._load()

    def _load(self) -> None:
        if not self._index.exists():
            return
        try:
            raw = json.loads(self._index.read_text(encoding="utf-8"))
            self._projects = {
                d["id"]: Project.from_dict(d)
                for d in raw.get("projects", []) if isinstance(d, dict)
            }
        except (OSError, ValueError, KeyError, TypeError):
            # 损坏不致命：备份后从空开始，避免整个 runtime 起不来
            try:
                self._index.replace(self._index.with_suffix(".json.corrupt"))
            except OSError:
                pass
            self._projects = {}

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.data_dir), prefix=".projects-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {"projects": [p.to_dict() for p in self._projects.values()]},
                    fh, ensure_ascii=False, indent=2, sort_keys=True,
                )
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._index)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def normalize_path(raw: str) -> Path:
        """校验并规范化宿主机文件夹路径：必须存在、是目录、绝对路径。"""
        if not raw or not str(raw).strip():
            raise ProjectError("文件夹路径不能为空")
        p = Path(str(raw)).expanduser()
        try:
            resolved = p.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProjectError(f"文件夹不存在或不可访问：{raw}") from exc
        if not resolved.is_dir():
            raise ProjectError(f"不是文件夹：{raw}")
        return resolved

    def create(self, name: str, folder: str) -> Project:
        path = self.normalize_path(folder)
        clean = str(name).strip() or path.name
        with _LOCK:
            for p in self._projects.values():
                if Path(p.path) == path:
                    raise ProjectError(f"该文件夹已是项目「{p.name}」，不能重复创建")
            pid = uuid.uuid4().hex[:12]
            proj = Project(id=pid, name=clean, path=str(path), created_at=_now())
            self._projects[pid] = proj
            self._save()
            return proj

    def get(self, project_id: str) -> Project | None:
        return self._projects.get(str(project_id))

    def list_projects(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: p.created_at)

    def delete(self, project_id: str) -> bool:
        with _LOCK:
            if str(project_id) not in self._projects:
                return False
            del self._projects[str(project_id)]
            self._save()
            return True

    def to_list(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.list_projects()]


def resolve_in_project(root: str | Path, path: str) -> Path:
    """把会话给出的路径解析到项目根内；越界（含符号链接逃逸）一律拒绝。"""
    base = Path(root).resolve()
    raw = Path(str(path or "")).expanduser()
    if not str(path or "").strip():
        return base
    candidate = (base / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if candidate == base or base in candidate.parents:
        return candidate
    raise ProjectError(f"路径不在项目文件夹内：{path}")
