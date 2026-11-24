"""Desktop IPC 协议 v1 的消息构造工具（与 docs/IPC-PROTOCOL.md 一一对应）。

纯数据层，不依赖 Qt / Tauri，可单测。
"""

from __future__ import annotations

import itertools
import json
from typing import Any, Iterator

PROTOCOL_VERSION = 1


class Seq:
    """每个 run 一个独立单调递增序号。"""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, str], Iterator[int]] = {}

    def for_run(self, task_id: str, run_id: str) -> int:
        key = (task_id, run_id)
        if key not in self._counters:
            self._counters[key] = itertools.count()
        return next(self._counters[key])

    def reset_run(self, task_id: str, run_id: str) -> None:
        self._counters.pop((task_id, run_id), None)


def encode(msg: dict[str, Any]) -> str:
    """一条消息 → 一行 JSON（ensure_ascii=False，紧凑）。"""
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n"


def ready(*, tools: list[str], sessions: list[dict[str, Any]],
          config: dict[str, Any], python: str) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION, "type": "ready", "protocol": PROTOCOL_VERSION,
        "python": python, "tools": tools, "sessions": sessions, "config": config,
    }


def status(task_id: str, run_id: str, seq: int, state: str,
           detail: str = "") -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION, "type": "status", "task_id": task_id,
        "run_id": run_id, "seq": seq, "state": state, "detail": detail,
    }


def event(task_id: str, run_id: str, seq: int, name: str,
          data: dict[str, Any]) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION, "type": "event", "task_id": task_id,
        "run_id": run_id, "seq": seq, "event": name, "data": data,
    }


def final(task_id: str, run_id: str, seq: int, text: str) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION, "type": "final", "task_id": task_id,
        "run_id": run_id, "seq": seq, "text": text,
    }


def error(stage: str, message: str, *, task_id: str = "",
          run_id: str = "", seq: int = -1) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION, "type": "error", "task_id": task_id,
        "run_id": run_id, "seq": seq, "stage": stage, "message": message,
    }


def approval_request(task_id: str, run_id: str, seq: int, tool: str,
                     question: str, detail: str = "") -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION, "type": "approval.request", "task_id": task_id,
        "run_id": run_id, "seq": seq, "tool": tool,
        "question": question, "detail": detail,
    }
