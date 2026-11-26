/** 技能包管理页：查看 skills.json 定义的技能与工具。 */

import { useCallback, useEffect, useState } from "react";
import { ipc } from "../lib/ipc";
import type { SkillStateMsg } from "../types/ipc";

export function SkillPage() {
  const [status, setStatus] = useState<SkillStateMsg["status"] | null>(null);
  const [text, setText] = useState("{\n  \"skills\": []\n}");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(() => {
    void ipc.getSkillStatus();
    void ipc.getSkillConfig();
  }, []);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "skill.state") setStatus(m.status);
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
