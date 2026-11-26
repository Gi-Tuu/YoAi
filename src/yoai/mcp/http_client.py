"""MCP Streamable HTTP 客户端（2025-06-18）。

每条 JSON-RPC 消息一次 POST；响应可以是 application/json 或 text/event-stream。
支持 Mcp-Session-Id、MCP-Protocol-Version、404 后重新初始化、DELETE 终止会话。
本阶段不主动开 GET SSE 订阅（tools-only 场景不需要）；通知通过 POST 响应流处理。
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from yoai.mcp.client import MCP_VERSION


def _parse_sse(body: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        payload = "\n".join(data_lines).strip()
        data_lines.clear()
        if not payload or payload == "[DONE]":
            return
        try:
            item = json.loads(payload)
        except ValueError:
            return
        if isinstance(item, dict):
            messages.append(item)

    for line in body.splitlines():
        if line == "":
            flush()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()
    return messages


class McpHttpClient:
    def __init__(
        self,
        name: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        timeout: float = 30.0,
        protocol_version: str = MCP_VERSION,
    ) -> None:
        self.name = name
        self.url = url
        self.headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.negotiated_version = protocol_version
        self.session_id = ""
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self._id = 0
        self._initialized = False

    @property
    def running(self) -> bool:
        return self._initialized

    async def start(self) -> None:
        if self._initialized:
            return
        result, _, _ = await self._post_request("initialize", {
            "protocolVersion": self.protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "YoAi", "version": "0.1.0"},
        }, allow_reinit=False)
        self.negotiated_version = str(result.get("protocolVersion") or self.protocol_version)
        self.capabilities = dict(result.get("capabilities") or {})
        self.server_info = dict(result.get("serverInfo") or {})
        await self.notify("notifications/initialized")
        self._initialized = True

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.negotiated_version,
            **self.headers,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post_sync(self, payload: dict[str, Any]) -> tuple[int, str, str, str]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=data, headers=self._base_headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return (response.status, response.headers.get("Content-Type", ""),
                        str(response.headers.get("Mcp-Session-Id", "")), body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            return (exc.code, exc.headers.get("Content-Type", ""),
                    str(exc.headers.get("Mcp-Session-Id", "")), body)

    async def _post(self, payload: dict[str, Any]) -> tuple[int, str, str, str]:
        return await asyncio.to_thread(self._post_sync, payload)

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result, _, _ = await self._post_request(method, params or {}, allow_reinit=True)
        return result

    async def _post_request(
        self, method: str, params: dict[str, Any], *, allow_reinit: bool,
    ) -> tuple[dict[str, Any], str, str]:
        self._id += 1
        request_id = self._id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            payload["params"] = params
        status, content_type, session, body = await self._post(payload)
        if status == 404 and self.session_id and allow_reinit:
            self.session_id = ""
            self._initialized = False
            await self.start()
            return await self._post_request(method, params, allow_reinit=False)
        if session and not self.session_id:
            self.session_id = session
        if status >= 400:
            raise RuntimeError(f"MCP HTTP {status}: {body[:300]}")
        if status == 202 or not body.strip():
            return {}, content_type, session
        message = self._message_from_body(body, content_type, request_id)
        if "error" in message:
            raise RuntimeError(f"MCP {self.name}.{method} 错误：{message['error']}")
        return dict(message.get("result") or {}), content_type, session

    @staticmethod
    def _message_from_body(body: str, content_type: str, request_id: int) -> dict[str, Any]:
        messages = []
        if "text/event-stream" in content_type:
            messages = _parse_sse(body)
        else:
            try:
                item = json.loads(body)
            except ValueError:
                item = {}
            messages = [item] if isinstance(item, dict) else []
        for message in messages:
            if str(message.get("id")) == str(request_id):
                return message
        return messages[-1] if messages else {}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        status, _, session, body = await self._post(payload)
        if session and not self.session_id:
            self.session_id = session
        if status >= 400:
            raise RuntimeError(f"MCP HTTP notify {status}: {body[:300]}")

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

    def _delete_sync(self) -> None:
        if not self.session_id:
            return
        request = urllib.request.Request(
            self.url, headers=self._base_headers(), method="DELETE")
        try:
            urllib.request.urlopen(request, timeout=self.timeout).close()
        except urllib.error.HTTPError as exc:
            if exc.code not in (405, 404):
                raise

    async def close(self) -> None:
        if self.session_id:
            try:
                await asyncio.to_thread(self._delete_sync)
            except Exception:  # noqa: BLE001
                pass
        self.session_id = ""
        self._initialized = False
