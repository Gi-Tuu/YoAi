"""YoAi Goal Manager — 跨会话长期目标与进度的持久化存储。

定位：计划书 §3.2 Goal Manager 模块的最小实现。
- 一个目标有 id / title / status / steps / 时间戳。
- status ∈ pending | active | done | cancelled。
- 与 Core 的 Planner 解耦：Core 规划"单次任务怎么执行"，这里管"跨会话要达成什么"。
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATUS = ("pending", "active", "done", "cancelled")


class GoalManager:
    """长期目标的 CRUD + 状态流转，JSON 原子写。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._goals: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._goals = raw
        except (json.JSONDecodeError, OSError):
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self._goals = {}

    def _save(self) -> None:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".yoai-goal-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._goals, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def create_goal(self, title: str, steps: list[str] | None = None) -> str:
        """创建一个长期目标，返回目标 id。steps 为可选步骤列表。"""
        goal_id = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat()
        self._goals[goal_id] = {
            "id": goal_id,
            "title": title,
            "status": "pending",
            "steps": list(steps or []),
            "created_at": now,
            "updated_at": now,
        }
        self._save()
        return goal_id

    def set_status(self, goal_id: str, status: str) -> bool:
        """变更目标状态。非法状态或不存在 id 返回 False。"""
        if status not in VALID_STATUS:
            return False
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        goal["status"] = status
        goal["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        return True

    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        """按 id 取目标详情。"""
        return self._goals.get(goal_id)

    def list_goals(self, status: str = "") -> list[dict[str, Any]]:
        """列出目标，可按 status 过滤。"""
        goals = list(self._goals.values())
        if status:
            goals = [g for g in goals if g["status"] == status]
        return sorted(goals, key=lambda g: g["created_at"])

    def active_goals(self) -> list[dict[str, Any]]:
        """列出所有进行中（pending / active）的目标。"""
        return [g for g in self.list_goals() if g["status"] in ("pending", "active")]

    def count(self) -> int:
        """统计目标总数。"""
        return len(self._goals)
