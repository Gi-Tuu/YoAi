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
from typing import Any, Callable

from yoai.shared_state import SharedJsonFile, synced

VALID_STATUS = ("pending", "active", "done", "cancelled")

# 目标变化监听（S5-1）：定时任务的「新建目标时 / 目标状态变化时」事件从这里来。
# 进程级列表：任何会话的 GoalManager 变化都会通知；回调异常只吞掉，不影响写入。
GoalListener = Callable[..., None]
_LISTENERS: list[GoalListener] = []


def add_goal_listener(listener: GoalListener) -> Callable[[], None]:
    """注册 listener(event, goal, manager, **extra)；返回取消注册的函数。

    event 为 "goal_created" 或 "goal_status_changed"（extra 带 old_status）。
    """
    _LISTENERS.append(listener)

    def remove() -> None:
        if listener in _LISTENERS:
            _LISTENERS.remove(listener)
    return remove


def _notify(event: str, goal: dict[str, Any], manager: "GoalManager", **extra: Any) -> None:
    for listener in list(_LISTENERS):
        try:
            listener(event, dict(goal), manager, **extra)
        except Exception:  # noqa: BLE001 - 监听方出错不能影响目标写入
            pass


class GoalManager(SharedJsonFile):
    """长期目标的 CRUD + 状态流转，JSON 原子写。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._goals: dict[str, dict[str, Any]] = {}
        self._init_shared()   # 多会话共享同一文件：读写前自动同步（见 shared_state.py）

    def _reset_state(self) -> None:
        self._goals = {}

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
        self._mark_saved()

    @synced
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
        _notify("goal_created", self._goals[goal_id], self)
        return goal_id

    @synced
    def set_status(self, goal_id: str, status: str) -> bool:
        """变更目标状态。非法状态或不存在 id 返回 False。"""
        if status not in VALID_STATUS:
            return False
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        old_status = goal.get("status", "")
        goal["status"] = status
        goal["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()
        if old_status != status:
            _notify("goal_status_changed", goal, self, old_status=old_status)
        return True

    @synced
    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        """按 id 取目标详情。"""
        return self._goals.get(goal_id)

    @synced
    def list_goals(self, status: str = "") -> list[dict[str, Any]]:
        """列出目标，可按 status 过滤。"""
        goals = list(self._goals.values())
        if status:
            goals = [g for g in goals if g["status"] == status]
        return sorted(goals, key=lambda g: g["created_at"])

    @synced
    def active_goals(self) -> list[dict[str, Any]]:
        """列出所有进行中（pending / active）的目标。"""
        return [g for g in self.list_goals() if g["status"] in ("pending", "active")]

    @synced
    def count(self) -> int:
        """统计目标总数。"""
        return len(self._goals)
