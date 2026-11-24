"""YoAi Desktop Runtime — Tauri ↔ YoAiAgent 的 JSONL IPC 桥。

职责边界（严格）：
- **不改内核**：只组装 YoAiAgent（复用 app.py 的 _build_main_model 语义），
  消费 astream 事件流，翻译成协议消息；Agent Loop / 工具 / 适配器零改动。
- **事件只用现有公开信息**：Core EventType + YoAi 的 thinking/delta。
- **进程生命周期**：stdin 读命令、stdout 只写协议行、stderr 写日志；
  shutdown 取消全部任务后退出。

启动（开发模式）：
    python apps/desktop-tauri/runtime/yoai_runtime.py

PYTHONPATH 需含 yoai 的 src 与 Core 的 src（脚本内会自动探测常见位置兜底）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# --- 路径自举：允许从 apps/desktop-tauri/runtime 直接运行 ---
_HERE = Path(__file__).resolve()
_YOAI_ROOT = _HERE.parents[2]          # apps/desktop-tauri/runtime → YoAi 根
for _p in (_YOAI_ROOT / "src", os.environ.get("YAI_CORE_SRC", "")):
    if _p and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from protocol import (  # noqa: E402  (自举后导入)
    PROTOCOL_VERSION, Seq, approval_request, encode, error, event, final,
    ready, status,
)


def _log(msg: str) -> None:
    """日志只走 stderr，stdout 保持协议纯净。"""
    print(f"[yoai-runtime] {msg}", file=sys.stderr, flush=True)


class Runtime:
    def __init__(self) -> None:
        self.seq = Seq()
        self.agent: Any = None
        self.sessions: Any = None
        self.tasks: dict[str, asyncio.Task] = {}       # run_id -> task
        self.running: dict[str, tuple[str, str]] = {}  # run_id -> (task_id, cancelled?)
        self.pending_approvals: dict[str, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()

    # ---- 输出 ----
    async def send(self, msg: dict[str, Any]) -> None:
        async with self._write_lock:
            sys.stdout.write(encode(msg))
            sys.stdout.flush()

    # ---- 构造 agent（复用桌面生产语义，不改内核）----
    def _ensure_agent(self) -> None:
        if self.agent is not None:
            return
        from yoai.agent import _default_data_dir
        from yoai.desktop.app import _agent_kwargs, _build_main_model
        from yoai.session import SessionManager
        from yai_core_sidecar_channel import make_sidecar_channel  # 本目录辅助

        data_dir = _default_data_dir()
        channel = make_sidecar_channel(self._request_host)
        provider, _archive = _build_main_model(data_dir)
        self.sessions = SessionManager(
            data_dir / "sessions",
            model_factory=lambda: provider,
            agent_kwargs=_agent_kwargs(data_dir, channel=channel),
        )
        self.agent = self.sessions.current_agent()

    async def _request_host(self, kind: str, payload: dict[str, Any]) -> Any:
        """SidecarChannel 回调：把审批/澄清发到前端并等待回答。"""
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        key = f"{kind}:{id(fut)}"
        self.pending_approvals[key] = fut
        if kind == "approval/request":
            task_id = self._current_task_id()
            run_id = self._current_run_id()
            seq = self.seq.for_run(task_id, run_id)
            await self.send(approval_request(
                task_id, run_id, seq,
                str(payload.get("tool", "")),
                "确认执行该操作？",
                json.dumps(payload, ensure_ascii=False)[:800],
            ))
        # clarify 走通用 event，前端用输入框回 reply
        elif kind == "clarify/request":
            await self.send(event(
                self._current_task_id(), self._current_run_id(),
                self.seq.for_run(self._current_task_id(), self._current_run_id()),
                "clarify_requested", payload,
            ))
        try:
            return await fut
        finally:
            self.pending_approvals.pop(key, None)

    def _current_task_id(self) -> str:
        return getattr(self, "_active_task_id", "")

    def _current_run_id(self) -> str:
        return getattr(self, "_active_run_id", "")

    # ---- 任务执行 ----
    async def start_task(self, task_id: str, run_id: str, user_input: str) -> None:
        try:
            self._ensure_agent()
        except Exception as exc:  # noqa: BLE001
            await self.send(error("startup", f"{type(exc).__name__}: {exc}",
                                  task_id=task_id, run_id=run_id))
            await self.send(status(task_id, run_id, -1, "failed", str(exc)))
            return

        self._active_task_id, self._active_run_id = task_id, run_id
        self.seq.reset_run(task_id, run_id)
        await self.send(status(task_id, run_id, self.seq.for_run(task_id, run_id),
                               "running"))

        async def _run() -> None:
            try:
                async for ev in self.agent.astream(user_input):
                    name = getattr(ev.type, "value", str(ev.type))
                    data = dict(getattr(ev, "data", {}) or {})
                    seq = self.seq.for_run(task_id, run_id)
                    if name == "done":
                        await self.send(final(task_id, run_id, seq,
                                              str(data.get("final_text", ""))))
                        await self.send(status(task_id, run_id,
                                               self.seq.for_run(task_id, run_id),
                                               "done"))
                    else:
                        await self.send(event(task_id, run_id, seq, name, data))
            except asyncio.CancelledError:
                await self.send(status(task_id, run_id,
                                       self.seq.for_run(task_id, run_id),
                                       "cancelled"))
            except Exception as exc:  # noqa: BLE001
                await self.send(error("runtime", f"{type(exc).__name__}: {exc}",
                                      task_id=task_id, run_id=run_id))
                await self.send(status(task_id, run_id,
                                       self.seq.for_run(task_id, run_id),
                                       "failed", str(exc)))

        task = asyncio.create_task(_run())
        self.tasks[run_id] = task
        task.add_done_callback(lambda _t: self.tasks.pop(run_id, None))

    def cancel_task(self, task_id: str, run_id: str) -> None:
        task = self.tasks.get(run_id)
        if task and not task.done():
            task.cancel()

    # ---- 命令分发 ----
    async def handle(self, cmd: dict[str, Any]) -> bool:
        """返回 False 表示要求退出。"""
        typ = cmd.get("type", "")
        task_id = str(cmd.get("task_id", ""))
        run_id = str(cmd.get("run_id", ""))

        if typ == "hello":
            self._ensure_agent()
            tools = self.agent.list_tools() if self.agent else []
            sessions = ([s.to_dict() for s in self.sessions.list()]
                        if hasattr(self.sessions, "list") else [])
            await self.send(ready(tools=[str(t) for t in tools],
                                  sessions=sessions, config={},
                                  python=sys.version.split()[0]))
        elif typ == "task.start":
            await self.start_task(task_id, run_id, str(cmd.get("input", "")))
        elif typ == "task.cancel":
            self.cancel_task(task_id, run_id)
        elif typ == "approval.reply" or typ == "clarify.reply":
            # 找到最早的待回复 future（前端一次只交互一项）
            for key, fut in list(self.pending_approvals.items()):
                if not fut.done():
                    value: Any = cmd.get("allow") if typ == "approval.reply" else cmd.get("answer", "")
                    if typ == "approval.reply":
                        value = bool(cmd.get("allow", False))
                    fut.set_result(value)
                    break
        elif typ == "shutdown":
            for task in list(self.tasks.values()):
                task.cancel()
            for fut in self.pending_approvals.values():
                if not fut.done():
                    fut.cancel()
            return False
        else:
            await self.send(error("protocol", f"unknown command: {typ}",
                                  task_id=task_id, run_id=run_id))
        return True


async def _stdin_commands(rt: Runtime, queue: asyncio.Queue) -> None:
    """阻塞读 stdin 放在 executor，避免卡住事件循环。"""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:      # EOF = 宿主关闭
            await queue.put({"type": "__eof__"})
            return
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                await queue.put(obj)
            else:
                await rt.send(error("protocol", "command must be an object"))
        except json.JSONDecodeError as exc:
            await rt.send(error("protocol", f"bad json: {exc}"))


async def amain() -> None:
    rt = Runtime()
    queue: asyncio.Queue = asyncio.Queue()
    reader = asyncio.create_task(_stdin_commands(rt, queue))
    try:
        while True:
            cmd = await queue.get()
            if cmd.get("type") == "__eof__":
                break
            if not await rt.handle(cmd):
                break
    finally:
        reader.cancel()
        for task in list(rt.tasks.values()):
            task.cancel()
        if rt.tasks:
            await asyncio.gather(*rt.tasks.values(), return_exceptions=True)


def main() -> int:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        import traceback
        _log(f"fatal: {type(exc).__name__}: {exc}")
        _log(traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
