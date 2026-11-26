"""MCP server 管理与工具桥接（YoAi 侧，Core 零改动）。

配置文件：<data_dir>/mcp/servers.json
{
  "servers": [
    {"name": "fs", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "<path>"],
     "enabled": true, "allowed_tools": [], "env": {}, "cwd": ""}
  ]
}
allowed_tools 为空表示全部；权限仍走 Core AllowlistPolicy/审批通道。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yai_core.types import ToolSpec

from yoai.mcp.client import McpClient
from yoai.mcp.http_client import McpHttpClient


@dataclass
class McpServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    enabled: bool = True
    allowed_tools: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "McpServerConfig":
        return cls(
            name=str(data.get("name", "")).strip(),
            transport=str(data.get("transport") or "stdio").strip().lower(),
            command=str(data.get("command", "")).strip(),
            args=[str(a) for a in (data.get("args") or [])],
            url=str(data.get("url", "")).strip(),
            headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
            cwd=str(data.get("cwd") or ""),
            enabled=bool(data.get("enabled", True)),
            allowed_tools=[str(t) for t in (data.get("allowed_tools") or [])],
        )


def _tool_name(server: str, tool: str) -> str:
    def clean(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", value).strip("_") or "x"
    base = f"mcp__{clean(server)}__{clean(tool)}"
    if len(base) <= 64:
        return base
    suffix = hashlib.sha1(f"{server}:{tool}".encode("utf-8")).hexdigest()[:8]
    return f"{base[:55].rstrip('_')}_{suffix}"


class McpManager:
    def __init__(self, data_dir: str | Path, *, timeout: float = 30.0) -> None:
        self.path = Path(data_dir) / "mcp" / "servers.json"
        self.timeout = timeout
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._clients: dict[str, McpClient] = {}
        self._specs: list[ToolSpec] = []
        self._mtime: float | None = None
        self._closed = False

    # --- 配置 ---
    def _load_configs(self) -> list[McpServerConfig]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        servers = raw.get("servers") if isinstance(raw, dict) else []
        if not isinstance(servers, list):
            return []
        result = []
        for item in servers:
            if not isinstance(item, dict):
                continue
            config = McpServerConfig.from_dict(item)
            configured = (config.command if config.transport == "stdio"
                          else config.url.startswith(("http://", "https://")))
            if config.name and config.transport in ("stdio", "http") and configured:
                result.append(config)
        return result

    def _config_mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime if self.path.exists() else None
        except OSError:
            return None

    # --- 后台事件循环 ---
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._closed:
                raise RuntimeError("McpManager 已关闭")
            if self._loop and self._loop.is_running():
                return self._loop
            self._ready.clear()

            def run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._ready.set()
                loop.run_forever()

            self._thread = threading.Thread(target=run, name="yoai-mcp", daemon=True)
            self._thread.start()
            self._ready.wait(timeout=5)
            assert self._loop is not None
            return self._loop

    def _run(self, coro) -> Any:
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=self.timeout + 10)

    # --- 生命周期 ---
    def refresh(self) -> list[ToolSpec]:
        """重新读取配置并重建 MCP 工具（坏 server 不影响其它 server）。"""
        self._run(self._refresh_async())
        with self._lock:
            return list(self._specs)

    async def _refresh_async(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()
        specs: list[ToolSpec] = []
        for config in self._load_configs():
            if not config.enabled:
                continue
            if config.transport == "http":
                client = McpHttpClient(
                    config.name, config.url, headers=config.headers,
                    timeout=self.timeout,
                )
            else:
                client = McpClient(
                    config.name, config.command, config.args,
                    env=config.env, cwd=config.cwd or None, timeout=self.timeout,
                )
            try:
                await client.start()
                tools = await client.list_tools()
            except Exception as exc:  # noqa: BLE001
                print(f"[mcp] {config.name} 不可用：{exc}", file=__import__("sys").stderr,
                      flush=True)
                await client.close()
                continue
            self._clients[config.name] = client
            allowed = set(config.allowed_tools)
            for tool in tools:
                name = str(tool.get("name", ""))
                if not name or (allowed and name not in allowed):
                    continue
                tool_name = _tool_name(config.name, name)
                handler = self._make_handler(config.name, name)
                specs.append(ToolSpec(
                    name=tool_name,
                    description=str(tool.get("description") or tool.get("title") or name),
                    input_schema=dict(tool.get("inputSchema") or {"type": "object"}),
                    handler=handler, source="mcp", version="v1",
                ))
        with self._lock:
            self._specs = specs
            self._mtime = self._config_mtime()

    def _make_handler(self, server: str, tool: str):
        def handler(**kwargs: Any) -> str:
            return self.call_tool(server, tool, kwargs)
        handler.__name__ = _tool_name(server, tool)
        handler.__doc__ = f"调用 MCP server {server} 的工具 {tool}。"
        return handler

    def tool_specs(self) -> list[ToolSpec]:
        """按需刷新：配置没变时直接返回缓存，不重连 server。"""
        with self._lock:
            if self._specs or self._mtime == self._config_mtime():
                return list(self._specs)
        return self.refresh()

    def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        client = self._clients.get(server)
        if client is None:
            return f"MCP server {server} 未连接"
        try:
            result = self._run(client.call_tool(tool, arguments))
        except Exception as exc:  # noqa: BLE001
            return f"MCP {server}.{tool} 调用失败：{exc}"
        blocks = result.get("content") or []
        parts = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind in ("image", "audio"):
                parts.append(f"[{kind} {block.get('mimeType', 'application/octet-stream')}]")
            elif kind == "resource_link":
                parts.append(f"[resource] {block.get('uri', '')}")
        if "structuredContent" in result:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        text = "\n".join(p for p in parts if p).strip()
        if result.get("isError"):
            return f"MCP 工具错误：{text or result}"
        return text or json.dumps(result, ensure_ascii=False)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "config": str(self.path),
                "servers": {
                    name: {"running": client.running,
                           "server_info": client.server_info,
                           "stderr_tail": list(getattr(client, "_stderr_tail", [])[-5:])}
                    for name, client in self._clients.items()
                },
                "tools": [spec.name for spec in self._specs],
            }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = self._loop
        if loop and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._close_async(), loop).result(timeout=10)
                loop.call_soon_threadsafe(loop.stop)
            except Exception:  # noqa: BLE001
                pass

    async def _close_async(self) -> None:
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()
