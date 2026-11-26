"""MCP stdio 客户端：JSON-RPC 2.0，标准 lifecycle + tools 能力。

只用标准库。stdout 只走 JSON-RPC；stderr 作为服务器日志隔离读取。
不实现 shell 解释、不把宿主全部环境变量（含网关 key）透传给 MCP server。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

MCP_VERSION = "2025-06-18"
_SAFE_ENV_KEYS = (
    "PATH", "SystemRoot", "TEMP", "TMP", "HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT",
    "ProgramFiles", "ProgramFiles(x86)",
)


def _safe_env(extra: dict[str, Any] | None) -> dict[str, str]:
    env: dict[str, str] = {}
    lower = {k.lower(): k for k in os.environ}
    for key in _SAFE_ENV_KEYS:
        actual = lower.get(key.lower())
        if actual:
            env[actual] = os.environ[actual]
    for key, value in (extra or {}).items():
        env[str(key)] = str(value)
    return env


class McpClient:
    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, Any] | None = None,
        cwd: str | Path | None = None,
        timeout: float = 30.0,
        protocol_version: str = MCP_VERSION,
    ) -> None:
        self.name = name
        self.command = command
        self.args = [str(a) for a in (args or [])]
        self.env = env or {}
        self.cwd = str(cwd) if cwd else None
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.process: asyncio.subprocess.Process | None = None
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: list[str] = []

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_safe_env(self.env), cwd=self.cwd,
            )
        except OSError as exc:
            raise RuntimeError(f"MCP server {self.name} 启动失败：{exc}") from exc
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        result = await self.request("initialize", {
            "protocolVersion": self.protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "YoAi", "version": "0.1.0"},
        })
        self.capabilities = dict(result.get("capabilities") or {})
        self.server_info = dict(result.get("serverInfo") or {})
        await self.notify("notifications/initialized")

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.process or not self.process.stdin:
            raise RuntimeError("MCP server 未启动")
        self._id += 1
        request_id = self._id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        try:
            response = await asyncio.wait_for(future, timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise RuntimeError(f"MCP {self.name}.{method} 超时") from exc
        if "error" in response:
            error = response["error"]
            raise RuntimeError(f"MCP {self.name}.{method} 错误：{error}")
        return dict(response.get("result") or {})

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.process or not self.process.stdin:
            return
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.process.stdin.drain()

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor = ""
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = await self.request("tools/list", params)
            tools.extend(result.get("tools") or [])
            cursor = str(result.get("nextCursor") or "")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.request("tools/call", {"name": name, "arguments": arguments})

    async def ping(self) -> bool:
        await self.request("ping")
        return True

    async def close(self) -> None:
        process = self.process
        if process is None:
            return
        self.process = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        if process.stdin:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            process.terminate()
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()

    async def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError):
                continue
            request_id = message.get("id")
            if request_id in self._pending:
                future = self._pending.pop(int(request_id))
                if not future.done():
                    future.set_result(message)

    async def _stderr_loop(self) -> None:
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            self._stderr_tail.append(line.decode("utf-8", "replace").strip())
            if len(self._stderr_tail) > 20:
                self._stderr_tail.pop(0)
            print(f"[{self.name}] {self._stderr_tail[-1]}", file=sys.stderr, flush=True)
