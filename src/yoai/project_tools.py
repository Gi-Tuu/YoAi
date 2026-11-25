"""项目模式的文件工具：proj_list / proj_read / proj_write / proj_patch。

与只读挂载（file_ro_*）的区别：本组工具**可写**，但严格限制在项目文件夹内；
写操作由权限档位决定要不要审批（full 放行、smart/manual 走 Core 审批通道）。

内核零改动：构造 ToolSpec 注册进 YoAi 侧工具表，与 readonly_tool_specs 同构。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from yai_core import build_spec

from yoai.project import ProjectError, resolve_in_project

_MAX_READ = 50000

# 写操作成功回调：由 runtime 注入，把操作记录到 FileChangeStore。
# 签名 (action, rel_path, before, after) -> None
OnChange = Callable[[str, str, str, str], None]


def project_tool_specs(
    root: str | Path, project_name: str = "", *, on_change: OnChange | None = None,
) -> list[Any]:
    """为项目构造 4 个工具 spec。root 必须是已校验的项目文件夹。"""
    base = Path(root).resolve()
    label = project_name or base.name

    def _preview(p: Path, action: str) -> str:
        # 审批弹窗看到的明细：动作 + 相对路径（不暴露宿主机绝对路径给模型输出）
        try:
            rel = p.relative_to(base).as_posix()
        except ValueError:
            rel = str(p)
        return json.dumps({"action": action, "path": rel, "project": label}, ensure_ascii=False)

    def proj_list(path: str = "") -> str:
        """列出项目文件夹内的文件与子目录（相对路径）。用户要查看项目结构时用。"""
        try:
            p = resolve_in_project(base, path)
        except ProjectError as exc:
            return str(exc)
        if not p.is_dir():
            return f"不是目录：{path}"
        return json.dumps(
            sorted(c.name + ("/" if c.is_dir() else "") for c in p.iterdir()),
            ensure_ascii=False,
        )

    def proj_read(path: str, max_chars: int = _MAX_READ) -> str:
        """读取项目文件夹内一个文本文件的内容，带 sha256。改文件前必须先读拿 sha256。"""
        try:
            p = resolve_in_project(base, path)
        except ProjectError as exc:
            return str(exc)
        if not p.is_file():
            return f"不是文件：{path}"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"读取失败：{type(exc).__name__}: {exc}"
        limit = max(500, min(_MAX_READ, int(max_chars)))
        return json.dumps({
            "path": path, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "content": text[:limit], "size": len(text),
            "detail": _preview(p, "read"),
        }, ensure_ascii=False)

    def proj_write(path: str, content: str) -> str:
        """在项目文件夹内新建文件（不覆盖已有文件）。已存在请改用 proj_patch。"""
        try:
            p = resolve_in_project(base, path)
        except ProjectError as exc:
            return str(exc)
        if p.exists():
            return f"文件已存在，请用 proj_patch：{path}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"写入失败：{type(exc).__name__}: {exc}"
        if on_change is not None:
            on_change("create", path, "", content)
        return json.dumps({
            "path": path, "created": True, "size": len(content),
            "detail": _preview(p, "write"),
        }, ensure_ascii=False)

    def proj_patch(path: str, content: str, expected_sha256: str) -> str:
        """整体改写项目内已存在文件。expected_sha256 必须是上次 proj_read 返回的 sha256
        （乐观并发：文件被改过会拒绝，需重新读取）。"""
        try:
            p = resolve_in_project(base, path)
        except ProjectError as exc:
            return str(exc)
        if not p.is_file():
            return f"不是文件：{path}"
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected_sha256:
            return f"冲突：文件已被修改（期望 {expected_sha256[:8]}，实际 {actual[:8]}），请重新 proj_read"
        try:
            before = p.read_text(encoding="utf-8", errors="replace")
            p.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"写入失败：{type(exc).__name__}: {exc}"
        if on_change is not None:
            on_change("patch", path, before, content)
        return json.dumps({
            "path": path, "updated": True, "size": len(content),
            "detail": _preview(p, "patch"),
        }, ensure_ascii=False)

    return [
        build_spec(proj_list),
        build_spec(proj_read),
        build_spec(proj_write),
        build_spec(proj_patch),
    ]


PROJECT_WRITE_TOOLS = {"proj_write", "proj_patch"}
PROJECT_READ_TOOLS = {"proj_list", "proj_read"}
