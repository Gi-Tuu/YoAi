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


# ---- v1 扩展（会话管理 / 通讯 / 星图）：旧消息全部不变，仅追加 ----

def snapshot(*, sessions: list[dict[str, Any]], current_id: str,
             history: list[dict[str, Any]], model: str,
             facts: dict[str, str], goals: list[dict[str, Any]],
             write_stats: dict[str, int], tools: list[str],
             thinking_log: list[dict[str, Any]] | None = None,
             projects: list[dict[str, Any]] | None = None,
             artifacts: list[dict[str, Any]] | None = None,
             changes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """会话全景状态：会话列表 + 当前历史 + 记忆侧栏数据 + 历史 thinking + 项目列表。"""
    return {
        "v": PROTOCOL_VERSION, "type": "snapshot",
        "sessions": sessions, "current_id": current_id,
        "history": history, "model": model,
        "facts": facts, "goals": goals,
        "write_stats": write_stats, "tools": tools,
        "thinking_log": thinking_log or [],
        "projects": projects or [],
        "artifacts": artifacts or [],
        "changes": changes or [],
    }


def file_changed(task_id: str, run_id: str, seq: int, *, record: dict[str, Any]) -> dict[str, Any]:
    """一次文件写操作完成（产物或改动），供前端实时追加卡片。"""
    return {
        "v": PROTOCOL_VERSION, "type": "file.changed",
        "task_id": task_id, "run_id": run_id, "seq": seq,
        "change": record,
    }


def chat_state(*, conversations: list[dict[str, Any]],
               external: list[dict[str, Any]]) -> dict[str, Any]:
    """通讯页全景：会话（单聊+群）与外部智能体注册表。"""
    return {
        "v": PROTOCOL_VERSION, "type": "chat.state",
        "conversations": conversations, "external": external,
    }


def chat_msg(*, target: str, sender: str, name: str, content: str,
             own: bool, at: str = "") -> dict[str, Any]:
    """一条聊天消息（含 runtime 收到的 peer 回复，主动推送）。"""
    return {
        "v": PROTOCOL_VERSION, "type": "chat.msg",
        "target": target, "sender": sender, "name": name,
        "content": content, "own": own, "at": at,
    }


def archive_state(*, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """进化档案星图：节点列表（depth 已算好，前端只画）。"""
    return {
        "v": PROTOCOL_VERSION, "type": "archive.state", "nodes": nodes,
    }


def permission_state(*, level: str, description: str) -> dict[str, Any]:
    """当前权限档位（三档：full/smart/manual）。"""
    return {
        "v": PROTOCOL_VERSION, "type": "permission.state",
        "level": level, "description": description,
    }


# ---- v1 扩展（右侧工具面板：浏览器 / 查看文件）----

def browser_opened(*, url: str) -> dict[str, Any]:
    """系统浏览器已接受打开请求（内嵌 iframe 被站点拒绝时的兜底）。"""
    return {
        "v": PROTOCOL_VERSION, "type": "browser.opened", "url": url,
    }


def file_tree(*, root: str, label: str, path: str,
              entries: list[dict[str, Any]]) -> dict[str, Any]:
    """文件视图的一级目录内容；path 为相对根的路径，条目带 name/path/is_dir。"""
    return {
        "v": PROTOCOL_VERSION, "type": "file.tree",
        "root": root, "label": label, "path": path, "entries": entries,
    }


def file_content(*, root: str, path: str, content: str,
                 size: int, truncated: bool) -> dict[str, Any]:
    """文件文本预览；仅文本、有长度上限，不返回二进制。"""
    return {
        "v": PROTOCOL_VERSION, "type": "file.content",
        "root": root, "path": path, "content": content,
        "size": size, "truncated": truncated,
    }
