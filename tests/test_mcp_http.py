"""MCP Streamable HTTP 传输测试：JSON 响应、SSE 响应、session 与 DELETE。"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yoai.mcp import McpHttpClient, McpManager, MCP_VERSION

TOOLS = [{"name": "echo", "description": "回显", "inputSchema": {"type": "object"}}]


class Handler(BaseHTTPRequestHandler):
    seen_sessions: list[str] = []
    seen_versions: list[str] = []
    deleted = False

    def log_message(self, *_args):
        return

    def _json(self, payload, status=200, session=""):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session:
            self.send_header("Mcp-Session-Id", session)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        msg = json.loads(self.rfile.read(length).decode("utf-8"))
        self.seen_versions.append(self.headers.get("MCP-Protocol-Version", ""))
        sid = self.headers.get("Mcp-Session-Id", "")
        if sid:
            self.seen_sessions.append(sid)
        method = msg.get("method")
        rid = msg.get("id")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            self._json({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": MCP_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-http", "version": "1"},
            }}, session="sess-http-1")
            return
        if method == "tools/list":
            body = (
                "event: message\n"
                'data: {"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n\n'
                "event: message\n"
                + "data: " + json.dumps({"jsonrpc": "2.0", "id": rid,
                                         "result": {"tools": TOOLS}}) + "\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if method == "tools/call":
            self._json({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": str((msg.get("params") or {}).get("arguments", {}).get("text", ""))}],
                "isError": False,
            }})
            return
        self._json({"jsonrpc": "2.0", "id": rid, "result": {}})

    def do_GET(self):  # noqa: N802
        body = (
            'id: evt-1\nevent: message\ndata: {"jsonrpc":"2.0",'
            '"method":"notifications/tools/list_changed"}\n\n'
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):  # noqa: N802
        Handler.deleted = True
        self.send_response(200)
        self.end_headers()


def _serve():
    Handler.seen_sessions = []
    Handler.seen_versions = []
    Handler.deleted = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}/mcp"


def test_http_client_json_sse_and_session():
    server, thread, url = _serve()
    try:
        async def scenario():
            client = McpHttpClient("http", url, timeout=10)
            await client.start()
            assert client.server_info["name"] == "fake-http"
            assert client.session_id == "sess-http-1"
            tools = await client.list_tools()
            assert [t["name"] for t in tools] == ["echo"]
            result = await client.call_tool("echo", {"text": "HTTP SSE"})
            assert result["content"][0]["text"] == "HTTP SSE"
            await client.close()
        asyncio.run(scenario())
        assert Handler.seen_sessions and all(s == "sess-http-1" for s in Handler.seen_sessions)
        assert all(v == MCP_VERSION for v in Handler.seen_versions)
        assert Handler.deleted is True
    finally:
        server.shutdown()
        thread.join(timeout=3)


def test_http_get_sse_notification():
    server, thread, url = _serve()
    try:
        async def scenario():
            seen = []
            client = McpHttpClient("http", url, timeout=10)
            client.on_notification = seen.append
            await client.start()
            await asyncio.sleep(1.2)
            await client.close()
            return seen
        seen = asyncio.run(scenario())
        assert any(m.get("method") == "notifications/tools/list_changed" for m in seen)
    finally:
        server.shutdown()
        thread.join(timeout=3)


def test_manager_supports_http_transport(tmp_path):
    server, thread, url = _serve()
    try:
        config = tmp_path / "mcp" / "servers.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"servers": [{
            "name": "http", "transport": "http", "url": url,
            "enabled": True, "allowed_tools": ["echo"],
        }]}), encoding="utf-8")
        manager = McpManager(tmp_path, timeout=10)
        try:
            specs = manager.tool_specs()
            assert [s.name for s in specs] == ["mcp__http__echo"]
            assert specs[0].handler(text="桥接") == "桥接"
        finally:
            manager.close()
    finally:
        server.shutdown()
        thread.join(timeout=3)
