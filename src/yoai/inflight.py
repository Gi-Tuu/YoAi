"""S5-2：记录进行中的对话轮次，应用被关掉 / 崩溃后，下次启动能找出被打断的那些。

参考 OpenClaw 的重启恢复：被打断的对话在重启后被检测出来。但 Core 没有断点 / checkpoint
接口，YoAi **做不到"从中间接着做"**，所以这里诚实地只做到：
- 记下每一轮的输入；正常结束（完成 / 失败 / 用户点停止）就删掉；
- 进程没来得及收尾（关应用、崩溃、被杀）就留下来，下次启动变成"被打断"；
- 界面提示「上次被中断」，用户可以**用同样的输入重新发送**，或者忽略。

文件：``data_dir/runs/inflight.json`` = ``{"running": {...}, "interrupted": {...}}``。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_INPUT_CHARS = 50_000     # 带附件的输入可能很长；超过就只存开头，界面不提供一键重发
MAX_KEEP = 5                 # 最多保留最近 5 条被打断的
MAX_AGE = timedelta(days=7)  # 7 天前的不再提示


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class InflightTurns:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "runs" / "inflight.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        raw = self._read()
        interrupted: dict[str, dict[str, Any]] = dict(raw.get("interrupted", {}))
        # 上一个进程留下的 running 都没来得及收尾 → 视为被打断
        for run_id, rec in dict(raw.get("running", {})).items():
            rec = dict(rec)
            rec["interrupted_at"] = _now()
            interrupted[run_id] = rec
        self._data: dict[str, dict[str, dict[str, Any]]] = {
            "running": {}, "interrupted": self._prune(interrupted)}
        self._write()

    # ---- 读写 ----
    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(v, dict)}

    def _write(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".yoai-inflight-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _prune(items: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - MAX_AGE
        fresh = [(k, v) for k, v in items.items()
                 if (_parse(v.get("interrupted_at", "")) or _parse(v.get("started_at", ""))
                     or datetime.now(timezone.utc)) >= cutoff]
        fresh.sort(key=lambda kv: str(kv[1].get("started_at", "")), reverse=True)
        return dict(fresh[:MAX_KEEP])

    # ---- 接口 ----
    def start(self, run_id: str, *, task_id: str, session_id: str, session_name: str,
              user_input: str) -> None:
        truncated = len(user_input) > MAX_INPUT_CHARS
        with self._lock:
            self._data["running"][run_id] = {
                "run_id": run_id, "task_id": task_id, "session_id": session_id,
                "session_name": session_name, "input": user_input[:MAX_INPUT_CHARS],
                "truncated": truncated, "started_at": _now(),
            }
            self._write()

    def finish(self, run_id: str) -> None:
        with self._lock:
            if self._data["running"].pop(run_id, None) is not None:
                self._write()

    def interrupted(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._data["interrupted"].values())
        return sorted((dict(v) for v in items), key=lambda v: str(v.get("started_at", "")), reverse=True)

    def dismiss(self, run_id: str) -> bool:
        with self._lock:
            if self._data["interrupted"].pop(run_id, None) is None:
                return False
            self._write()
            return True
