"""Agent 文件操作记录：产物（新建）+ 改动（修改），带行级 diff。

设计（2026-11-25 所有者拍板接入产品）：
- 智能体读写文件后，用户要能像主流 IDE Agent 一样看到"N 个文件已修改"、
  逐文件 +X/-Y，点开展示行级 diff；新建文件登记为"产物"可预览/下载。
- 这是产品侧能力，内核零改动：在 YoAi 的 proj_* 工具 handler 旁边记录，
  落盘 <data_dir>/file_changes.jsonl，按会话/项目可查。

记录内容：
- 每条 = 一次写操作（create/patch），含 before/after 全文（用于行级 diff 和预览）、
  added/removed 行数、时间、session_id、project_id。
- 存储上限（默认 200 条）防止源码全文无限膨胀；超出裁剪最旧。
"""

from __future__ import annotations

import difflib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
MAX_RECORDS = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def line_diff(before: str, after: str) -> tuple[int, int, list[dict[str, Any]]]:
    """行级 diff：返回 (added, removed, operations)。

    operations 每项 {kind: context|add|remove, text, old_line?, new_line?}，
    前端按顺序渲染即可（绿色 + / 红色 -）。用 SequenceMatcher 逐行比对。
    """
    old = before.splitlines()
    new = after.splitlines()
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    ops: list[dict[str, Any]] = []
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                ops.append({"kind": "context", "text": old[i1 + k],
                            "old_line": i1 + k + 1, "new_line": j1 + k + 1})
        elif tag in ("replace", "delete"):
            for k in range(i1, i2):
                removed += 1
                ops.append({"kind": "remove", "text": old[k], "old_line": k + 1})
        if tag in ("replace", "insert"):
            for k in range(j1, j2):
                added += 1
                ops.append({"kind": "add", "text": new[k], "new_line": k + 1})
    return added, removed, ops


class FileChangeStore:
    """文件操作记录：追加 + 按会话查询 + 裁剪。纯标准库，可单测。"""

    def __init__(self, data_dir: str | Path, max_records: int = MAX_RECORDS) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "file_changes.jsonl"
        self.max_records = max(1, int(max_records))

    def append(
        self, *, session_id: str, project_id: str, path: str, action: str,
        before: str = "", after: str = "", run_id: str = "",
    ) -> dict[str, Any]:
        """记录一次写操作。action: create | patch。"""
        added, removed, ops = line_diff(before, after)
        rec: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "at": _now(),
            "session_id": str(session_id),
            "project_id": str(project_id),
            "run_id": str(run_id),
            "path": str(path),
            "action": str(action),
            "added": added,
            "removed": removed,
            "before": before,
            "after": after,
            "diff": ops,
        }
        with _LOCK:
            records = self._load_unlocked()
            records.append(rec)
            # 裁剪：保留最近 max_records 条
            records = records[-self.max_records:]
            fd, tmp = tempfile.mkstemp(dir=str(self.data_dir), prefix=".changes-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    for r in records:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        return rec

    def _load_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    if isinstance(d, dict):
                        out.append(d)
                except (ValueError, TypeError):
                    continue
        except OSError:
            return []
        return out

    def load(self, *, session_id: str = "", project_id: str = "") -> list[dict[str, Any]]:
        """查询记录（可按会话/项目过滤），新的在前。"""
        with _LOCK:
            records = self._load_unlocked()
        if session_id:
            records = [r for r in records if r.get("session_id") == session_id]
        if project_id:
            records = [r for r in records if r.get("project_id") == project_id]
        return list(reversed(records))

    def summary(self, *, session_id: str = "", project_id: str = "") -> dict[str, Any]:
        """汇总：产物（create）与改动（patch），供 snapshot 推送。"""
        records = self.load(session_id=session_id, project_id=project_id)
        artifacts = [r for r in records if r.get("action") == "create"]
        changes = [r for r in records if r.get("action") == "patch"]
        return {
            "artifacts": [self._public(r) for r in artifacts],
            "changes": [self._public(r) for r in changes],
        }

    @staticmethod
    def _public(rec: dict[str, Any]) -> dict[str, Any]:
        """对外字段：diff 保留供展开；产物(create)带 after 全文供下载/预览，
        改动(patch)不带全文（snapshot 体积考虑，diff 已够展示）。"""
        out = {
            k: rec.get(k) for k in
            ("id", "at", "path", "action", "added", "removed", "diff",
             "session_id", "project_id", "run_id")
        }
        if rec.get("action") == "create":
            out["after"] = rec.get("after", "")
        return out

    def clear(self) -> None:
        with _LOCK:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
