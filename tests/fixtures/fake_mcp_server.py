"""最小 MCP stdio server 测试夹具：支持 initialize/tools/list/tools/call。"""

import json
import sys

TOOLS = [{
    "name": "echo",
    "description": "回显参数",
    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
}]


def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": str(args.get("text", ""))}],
                "isError": False,
            }})
        else:
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"unknown tool {name}"}],
                "isError": True,
            }})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
