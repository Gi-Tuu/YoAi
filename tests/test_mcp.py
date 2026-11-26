"""MCP 标准协议客户端与工具桥接守护测试（fake stdio server）。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from yoai.mcp import McpClient, McpManager, MCP_VERSION

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


def _client() -> McpClient:
    return McpClient("fake", sys.executable, [str(FIXTURE)], timeout=10)


def test_mcp_client_lifecycle_list_and_call():
    async def scenario():
        client = _client()
        await client.start()
        try:
            assert client.server_info["name"] == "fake-mcp"
            assert "tools" in client.capabilities
            tools = await client.list_tools()
            assert [t["name"] for t in tools] == ["echo"]
            result = await client.call_tool("echo", {"text": "你好 mcp"})
            assert result["content"][0]["text"] == "你好 mcp"
            assert await client.ping() is True
        finally:
            await client.close()

    asyncio.run(scenario())


def test_mcp_manager_registers_tool_spec(tmp_path):
    config = tmp_path / "mcp" / "servers.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"servers": [{
        "name": "fake", "command": sys.executable,
        "args": [str(FIXTURE)], "enabled": True,
    }]}, ensure_ascii=False), encoding="utf-8")

    manager = McpManager(tmp_path, timeout=10)
    try:
        specs = manager.tool_specs()
        assert len(specs) == 1
        assert specs[0].name == "mcp__fake__echo"
        assert specs[0].source == "mcp"
        assert specs[0].handler(text="桥接成功") == "桥接成功"
        status = manager.status()
        assert status["tools"] == ["mcp__fake__echo"]
        assert status["servers"]["fake"]["running"] is True
    finally:
        manager.close()


def test_mcp_version_is_standard():
    assert MCP_VERSION == "2025-06-18"
