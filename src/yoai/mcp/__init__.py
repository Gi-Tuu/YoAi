"""YoAi MCP 客户端包（标准 JSON-RPC 协议，YoAi 侧扩展，Core 零改动）。"""

from yoai.mcp.client import McpClient, MCP_VERSION
from yoai.mcp.http_client import McpHttpClient
from yoai.mcp.manager import McpManager, McpServerConfig

__all__ = ["McpClient", "McpHttpClient", "MCP_VERSION", "McpManager", "McpServerConfig"]
