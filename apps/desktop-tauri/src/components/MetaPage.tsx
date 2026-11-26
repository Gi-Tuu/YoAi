/** R4 元策略页：查看阈值版本、发起提案、人工批准。 */

import { useCallback, useEffect, useState } from "react";
import { ipc } from "../lib/ipc";
import type { RsiMetaStateMsg } from "../types/ipc";

export function MetaPage() {
  const [status, setStatus] = useState<RsiMetaStateMsg["status"] | null>(null);
  const [notice, setNotice] = useState("");

  const refresh = useCallback(() => { void ipc.getMetaPolicy(); }, []);
  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "rsi.meta.state") setStatus(m.status);
      if (m.type === "rsi.meta.ack") setNotice(m.message);
      if (m.type === "error" && m.stage === "message") setNotice(m.message);
    });
    refresh();
    return off;
  }, [refresh]);

  const active = status?.active ?? null;
  const versions = status?.versions ?? [];

  return (
    <div className="mcp-page">
      <header className="boundary-head">
        <div>
          <h2>元策略</h2>
          <p>进化规则本身的版本化 · 新版本只进候选，需人工批准才生效</p>
        </div>
        <button type="button" onClick={refresh}>↻ 刷新</button>
      </header>
      {notice && <div className="boundary-notice">{notice}</div>}

      <section className="mcp-card" style={{ marginBottom: "var(--sp-3)" }}>
        <h3>当前生效：v{active?.version ?? "—"}</h3>
        {active && (
          <div className="meta-grid">
            {Object.entries(active).filter(([k]) => k !== "version" && k !== "reason"
              && k !== "parent_id" && k !== "created_at").map(([key, value]) => (
              <div key={key}><span>{key}</span><b>{String(value)}</b></div>
            ))}
          </div>
        )}
        <div className="mcp-actions">
          <button type="button" onClick={() => void ipc.proposeMetaPolicy()}>生成候选提案</button>
        </div>
      </section>

      <section className="mcp-card">
        <h3>版本历史（{versions.length}）</h3>
        {versions.map((policy) => (
          <div key={String(policy.version)} className="mcp-server">
            <div>
              <b>v{String(policy.version)}</b>
              <span>{policy.version === active?.version ? "生效中" : "候选/历史"}</span>
            </div>
            <div className="mcp-meta">{String(policy.reason ?? "")}</div>
            {policy.version !== active?.version && (
              <button type="button" className="boundary-trigger"
                      onClick={() => void ipc.approveMetaPolicy(Number(policy.version))}>
                批准此版本
              </button>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
