/** MCP 管理页：查看 server/tool 状态并编辑 servers.json。 */

import { useCallback, useEffect, useState } from "react";
import { ipc } from "../lib/ipc";
import type { McpStateMsg } from "../types/ipc";

export function McpPage() {
  const [status, setStatus] = useState<McpStateMsg["status"] | null>(null);
  const [text, setText] = useState("{\n  \"servers\": []\n}");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(() => {
    void ipc.getMcpStatus();
    void ipc.getMcpConfig();
  }, []);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "mcp.state") setStatus(m.status);
      if (m.type === "mcp.config") setText(m.text);
      if (m.type === "mcp.ack") setNotice(m.message);
      if (m.type === "error" && m.stage === "mcp") setNotice(m.message);
    });
    refresh();
    return off;
  }, [refresh]);

  const servers = Object.entries(status?.servers ?? {});
  const tools = status?.tools ?? [];

  return (
    <div className="mcp-page">
      <header className="boundary-head">
        <div>
          <h2>MCP 扩展</h2>
          <p>标准协议接入外部工具 · 配置保存在本地 · 写入后立即重载</p>
        </div>
        <button type="button" onClick={refresh}>↻ 刷新</button>
      </header>
      {notice && <div className="boundary-notice">{notice}</div>}

      <div className="mcp-grid">
        <section className="mcp-card">
          <h3>Server 状态</h3>
          {servers.length === 0 && <div className="side-empty">还没有配置 MCP server。</div>}
          {servers.map(([name, info]) => (
            <div key={name} className="mcp-server">
              <div>
                <b>{name}</b>
                <span className={info.running ? "mcp-on" : "mcp-off"}>
                  {info.running ? "运行中" : "未运行"}
                </span>
              </div>
              <div className="mcp-meta">{JSON.stringify(info.server_info)}</div>
              {info.stderr_tail.length > 0 && (
                <pre className="mcp-stderr">{info.stderr_tail.join("\n")}</pre>
              )}
            </div>
          ))}
        </section>

        <section className="mcp-card">
          <h3>已注册工具（{tools.length}）</h3>
          {tools.length === 0 && <div className="side-empty">暂无 MCP 工具。</div>}
          <div className="mcp-tools">
            {tools.map((tool) => <code key={tool}>{tool}</code>)}
          </div>
        </section>
      </div>

      <section className="mcp-card mcp-config">
        <h3>servers.json</h3>
        <textarea value={text} onChange={(e) => setText(e.target.value)}
                  aria-label="MCP 配置" spellCheck={false} />
        <div className="mcp-actions">
          <button type="button" onClick={() => void ipc.setMcpConfig(text)}>保存并重载</button>
          <button type="button" onClick={() => void ipc.reloadMcp()}>仅重载</button>
        </div>
        <p className="boundary-note">
          配置不会上传。headers 里可放本地 token，但日志不会回显配置内容。
        </p>
      </section>
    </div>
  );
}
