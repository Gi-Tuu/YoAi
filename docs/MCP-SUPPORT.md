# MCP 标准协议支持（stdio + Streamable HTTP + tools）

> 2026-11-26。YoAi 侧扩展，Core 零改动。遵循 MCP JSON-RPC 2.0（2025-06-18）。

## 已实现

- **传输**：stdio（换行分隔 JSON-RPC 2.0）与 Streamable HTTP；
- **HTTP 细节**：每条消息一次 POST，`Accept: application/json, text/event-stream`，
  `MCP-Protocol-Version` 头，`Mcp-Session-Id` 会话保持，响应支持 JSON 或 SSE，
  404 自动重新初始化，DELETE 显式终止会话；
- **生命周期**：`initialize` → `notifications/initialized` → 正常操作 → 关闭 stdin 优雅退出，超时强杀；
- **协议版本**：请求 `2025-06-18`（广泛兼容的稳定版本）；
- **能力**：`tools/list`（支持 `nextCursor` 分页）、`tools/call`、`ping`；
- **工具桥接**：外部工具注册为 Core `ToolSpec(source="mcp")`，名称 `mcp__<server>__<tool>`；
- **权限**：MCP 工具走 Core `AllowlistPolicy` / 桌面审批通道，不绕过三档权限；
- **配置热更新**：`mcp/servers.json` mtime 变化时自动重连并重建工具，不影响其它工具；
- **进程隔离**：MCP server 子进程由专用后台事件循环管理；退出 runtime 时统一关闭。

## 配置

路径：`<data_dir>/mcp/servers.json`，桌面生产通常是：

```
<exe所在目录>/output/mcp/servers.json
```

示例：

```json
{
  "servers": [
    {
      "name": "fs",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
      "enabled": true,
      "allowed_tools": [],
      "env": {},
      "cwd": ""
    }
  ]
}
```

HTTP server 示例：

```json
{
  "servers": [
    {
      "name": "remote",
      "transport": "http",
      "url": "https://example.com/mcp",
      "headers": {"Authorization": "Bearer <token>"},
      "enabled": true,
      "allowed_tools": []
    }
  ]
}
```

- `name`：唯一标识；
- `transport`：`stdio`（默认）或 `http`；stdio 用 `command` + `args`，**不经过 shell**；
- HTTP 用 `url`，可选 `headers`（本地配置，不写日志）；
- `allowed_tools`：空数组表示全部；非空时只注册列出的工具；
- `env`：追加给子进程的环境变量（不建议放真实密钥）。

## 安全边界

- 不透传宿主完整环境变量：只给 PATH/SystemRoot/TEMP/HOME/APPDATA 等白名单键 + 显式 `env`；
- server 的 stdout 只解析协议 JSON；stderr 作为日志隔离读取；
- 工具描述与 annotations 视为不可信文本，只展示、不自动执行；
- 坏 server / 坏工具不会让主对话失败，启动时打印到 stderr 并跳过；
- 不支持 shell 展开、远程安装或自动下载 server；用户需自行准备好命令。

## 明确未做

- SSE GET 主动订阅（server 主动推送的独立流）；当前只在 POST 响应流里处理通知/响应，tools 场景足够；
- OAuth 自动发现与完整认证流程（可通过 `headers` 手动提供 token）；
- resources / prompts / sampling / elicitation / logging 能力；
- MCP server 的 UI 安装与管理页面；
- 把 MCP 工具自动纳入 RSI 候选（可后续做）。

## 测试

- `tests/test_mcp.py`：fake stdio server 验证 initialize、tools/list、tools/call、ping、
  ToolSpec 桥接与 manager 状态。
- `tests/test_mcp_http.py`：fake Streamable HTTP server 验证 JSON/SSE 响应、session 头、
  MCP-Protocol-Version、DELETE 终止与 manager HTTP 配置。
