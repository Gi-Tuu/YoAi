"""Thinking 持久化（YoAi 侧，不改内核）。

Core 的 history 只存最终文本，thinking 块不落库——导致历史消息里看不到思考。
本模块在 runtime 收到 thinking 事件时按 run 累积，done 后追加到
``<data_dir>/sessions/thinking/<session_id>.jsonl``：

    {"run_id": "...", "session_id": "...", "at": "...", "text": "...", "input": "..."}

读取时按 session_id 返回全部记录，snapshot 携带给前端展示。
文件追加写 + 上限裁剪（保留最近 500 条），避免无限增长。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_RECORDS = 500


class ThinkingStore:
    def __init__(self, data_dir: Path) -> None:
        self.dir = Path(data_dir) / "sessions" / "thinking"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, session_id: str) -> Path:
        # session_id 是 uuid hex，安全；仍做一次字符过滤防路径穿越
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.dir / f"{safe}.jsonl"

    def append(self, *, session_id: str, run_id: str, text: str,
               user_input: str = "") -> None:
        if not session_id or not text.strip():
            return
        record = {
            "run_id": run_id,
            "session_id": session_id,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "text": text,
            "input": user_input[:200],
        }
        with self._lock:
            path = self._path(session_id)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._trim(path)

    def _trim(self, path: Path) -> None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= MAX_RECORDS:
                return
            path.write_text("\n".join(lines[-MAX_RECORDS:]) + "\n", encoding="utf-8")
        except OSError:
            pass

    def load(self, session_id: str) -> list[dict[str, Any]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        with self._lock:
            try:
                out: list[dict[str, Any]] = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            out.append(obj)
                    except json.JSONDecodeError:
                        continue
                return out
            except OSError:
                return []
