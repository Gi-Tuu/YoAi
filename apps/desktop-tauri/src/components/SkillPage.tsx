/** 技能包管理页：查看 skills.json 定义的技能与工具。 */

import { useCallback, useEffect, useState } from "react";
import { open as openDir } from "@tauri-apps/plugin-dialog";
import { ipc } from "../lib/ipc";
import type { SkillMarketStateMsg, SkillStateMsg } from "../types/ipc";

export function SkillPage() {
  const [status, setStatus] = useState<SkillStateMsg["status"] | null>(null);
  const [market, setMarket] = useState<SkillMarketStateMsg["status"] | null>(null);
  const [text, setText] = useState("{\n  \"skills\": []\n}");
  const [notice, setNotice] = useState("");
  const [remoteUrl, setRemoteUrl] = useState("");

  const refresh = useCallback(() => {
    void ipc.getSkillStatus();
    void ipc.getSkillConfig();
    void ipc.getSkillMarket();
  }, []);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "skill.state") setStatus(m.status);
      if (m.type === "skill.market.state") setMarket(m.status);
      if (m.type === "skill.config") setText(m.text);
      if (m.type === "skill.ack") setNotice(m.message);
      if (m.type === "error" && m.stage === "skill") setNotice(m.message);
    });
    refresh();
    return off;
  }, [refresh]);

  const skills = status?.skills ?? [];
  const tools = status?.tools ?? [];

  return (
    <div className="mcp-page">
      <header className="boundary-head">
        <div>
          <h2>技能包</h2>
          <p>按需加载提示词与建议工具 · 配置保存在本地 · 不自动授权</p>
        </div>
        <button type="button" onClick={refresh}>↻ 刷新</button>
      </header>
      {notice && <div className="boundary-notice">{notice}</div>}

      <section className="mcp-card" style={{ marginBottom: "var(--sp-3)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3>技能市场（{market?.items.length ?? 0}）</h3>
          <div className="mcp-actions">
            <input value={remoteUrl} onChange={(e) => setRemoteUrl(e.target.value)}
                   placeholder="https://…/catalog.json" aria-label="远程市场地址" />
            <button type="button" disabled={!remoteUrl.trim()}
                    onClick={() => void ipc.addRemoteSkillMarket(remoteUrl.trim())}>添加远程源</button>
            <button type="button" onClick={() => void ipc.refreshRemoteSkillMarket()}>刷新远程</button>
            <button type="button" onClick={() => void (async () => {
              const picked = await openDir({ directory: true, multiple: false, title: "选择技能包目录" });
              if (picked && typeof picked === "string") await ipc.addSkillMarket(picked);
            })()}>登记本地包</button>
          </div>
        </div>
        {(market?.items.length ?? 0) === 0 && <div className="side-empty">市场为空。可发布当前技能或登记本地包。</div>}
        {market?.items.map((item) => (
          <div key={item.name} className="mcp-server">
            <div><b>{item.name}</b><span>v{item.version}</span></div>
            <div className="mcp-meta">{item.description}</div>
            <div className="mcp-meta">来源：{item.source_type ?? "local"} · lock：{item.lock_exists ? "已生成" : "未生成"} · {item.source}</div>
            <div className="mcp-actions">
              <button type="button" onClick={() => void ipc.installMarketSkill(item.name)}>安装</button>
              <button type="button" onClick={() => void ipc.removeMarketSkill(item.name)}>移出市场</button>
            </div>
          </div>
        ))}
      </section>

      <div className="mcp-grid">
        <section className="mcp-card">
          <h3>可用技能（{skills.length}）</h3>
          {skills.length === 0 && <div className="side-empty">还没有配置技能。</div>}
          {skills.map((skill) => (
            <div key={skill.name} className="mcp-server">
              <div><b>{skill.name}</b><span>{skill.description}</span></div>
              <div className="mcp-meta">建议工具：{skill.tools.join(", ") || "无"}</div>
              <div className="mcp-meta">脚本：{status?.skills.find((s) => s.name === skill.name)?.scripts?.join(", ") || "无"}</div>
              <div className="mcp-meta">资源：{status?.skills.find((s) => s.name === skill.name)?.resources?.join(", ") || "无"}</div>
              <div className="mcp-meta">
                requirements：{status?.dependencies?.[skill.name]?.requirements_exists ? "已生成" : "未生成"}
                · lock：{status?.dependencies?.[skill.name]?.lock_exists ? "已生成" : "未生成"}
              </div>
              <div className="mcp-actions">
                <button type="button" onClick={() => void ipc.generateSkillRequirements(skill.name)}>生成 requirements</button>
                <button type="button" onClick={() => void ipc.generateSkillLock(skill.name)}>生成 lockfile</button>
                <button type="button" onClick={() => void ipc.publishMarketSkill(skill.name)}>发布到市场</button>
              </div>
              <pre className="mcp-stderr">{skill.prompt}</pre>
            </div>
          ))}
        </section>
        <section className="mcp-card">
          <h3>技能工具（{tools.length}）</h3>
          {tools.length === 0 && <div className="side-empty">暂无技能工具。</div>}
          <div className="mcp-tools">{tools.map((t) => <code key={t}>{t}</code>)}</div>
        </section>
      </div>

      <section className="mcp-card mcp-config">
        <h3>skills.json</h3>
        <textarea value={text} onChange={(e) => setText(e.target.value)}
                  aria-label="技能配置" spellCheck={false} />
        <div className="mcp-actions">
          <button type="button" onClick={() => void ipc.setSkillConfig(text)}>保存并重载</button>
          <button type="button" onClick={() => void ipc.reloadSkills()}>仅重载</button>
        </div>
        <p className="boundary-note">
          技能第一阶段只提供提示词与建议工具；工具调用仍走当前权限档位。
        </p>
      </section>
    </div>
  );
}
