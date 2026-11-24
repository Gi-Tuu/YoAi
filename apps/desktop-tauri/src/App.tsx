/** YoAi 下一代桌面工作台（Tauri + React）。
 *  旧 PySide6 端保留不动——本目录是独立新工程。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ipc } from "./lib/ipc";
import { useTaskStream, type RunState } from "./hooks/useTaskStream";
import { ProcessPanel } from "./components/ProcessPanel";
import { Markdown } from "./components/Markdown";
import type { RuntimeMsg } from "./types/ipc";

const newId = (p: string) => `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;

function toolCards(run: RunState) {
  return run.events.filter((e) => e.name === "tool_call" || e.name === "tool_result");
}

function ChatRun({ run, streaming }: { run: RunState; streaming: boolean }) {
  const rounds = useMemo(() => [...run.streamText.entries()].sort((a, b) => a[0] - b[0]), [run.streamText]);
  return (
    <article className="chat-run">
      <header className="run-head">
        <span className="who">YoAi</span>
        <span className="state" data-state={run.state}>{run.state}</span>
        <span className="run-time">{new Date(run.startedAt).toLocaleTimeString("zh-CN")}</span>
      </header>

      <ProcessPanel events={run.events} thinking={run.thinking} />

      {/* 流式文本：每轮一段；完成后以 final 定稿为准，避免重复 */}
      {streaming && rounds.map(([round, text]) => text && (
        <div key={round} className="stream-block"><Markdown text={text} streaming /></div>
      ))}

      {run.finalText && <div className="final-answer"><Markdown text={run.finalText} /></div>}

      {toolCards(run).length > 0 && (
        <div className="tool-cards">
          {toolCards(run).slice(-4).map((e) => (
            <div key={e.seq} className={`tool-card ${e.name}`}>
              <span className="tool-icon">{e.name === "tool_call" ? "→" : "←"}</span>
              <span>{String(e.data.tool ?? "")}</span>
            </div>
          ))}
        </div>
      )}

      {run.approval && (
        <div className="approval-box">
          <p>{run.approval.question} <code>{run.approval.tool}</code></p>
          <div>
            <button onClick={() => { void ipc.replyApproval(run.taskId, run.runId, true); }}>允许</button>
            <button onClick={() => { void ipc.replyApproval(run.taskId, run.runId, false); }}>拒绝</button>
          </div>
        </div>
      )}
    </article>
  );
}

export default function App() {
  const [msgs, setMsgs] = useState<RuntimeMsg[]>([]);
  const [input, setInput] = useState("");
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState("");
  const [floating, setFloating] = useState(false);
  const [specialist, setSpecialist] = useState("通用根");
  const { runs, activeRunId, beginRun } = useTaskStream(msgs);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      setMsgs((prev) => [...prev, m]);
      if (m.type === "ready") setReady(true);
      if (m.type === "error") setErr(m.message);
    });
    void ipc.connect().catch((e) => setErr(String(e)));
    return () => { off(); void ipc.shutdown().catch(() => {}); };
  }, []);

  const send = useCallback(() => {
    const text = input.trim();
    if (!text || !ready) return;
    const taskId = newId("t"); const runId = newId("r");
    beginRun(taskId, runId, text);
    setMsgs([]);  // 本轮视图切换到新 run；历史由 run Map 保留
    void ipc.startTask(taskId, runId, text).catch((e) => setErr(String(e)));
    setInput("");
  }, [input, ready, beginRun]);

  const cancel = useCallback(() => {
    const run = runs.get(activeRunId);
    if (run) void ipc.cancelTask(run.taskId, run.runId).catch((e) => setErr(String(e)));
  }, [runs, activeRunId]);

  const active = runs.get(activeRunId);
  const runList = useMemo(() => [...runs.values()], [runs]);

  if (floating) {
    return (
      <div className="capsule" onClick={() => setFloating(false)} title="点击展开主面板">
        <span className="capsule-dot" data-state={active?.state ?? "idle"} />
        <span>{active ? `${active.state} · ${active.events.length} 步` : "YoAi 待命"}</span>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">YoAi <span className="tag">工作台</span></div>
        <div className="top-actions">
          <select value={specialist} onChange={(e) => setSpecialist(e.target.value)} title="专员切换">
            <option>通用根</option><option>写作</option><option>研究</option>
          </select>
          <button onClick={() => setFloating(true)} title="切换悬浮模式">◱ 悬浮</button>
        </div>
      </header>

      {err && <div className="error-bar">⚠ {err}</div>}
      {!ready && <div className="boot-bar">正在连接 Python Runtime…</div>}

      <main className="workspace">
        <div className="chat-scroll">
          {runList.length === 0 && (
            <div className="empty">输入一个任务，开始与 YoAi 对话。</div>
          )}
          {runList.map((run) => (
            <div key={run.runId}>
              <div className="user-msg">{run.input}</div>
              <ChatRun run={run} streaming={run.runId === activeRunId} />
            </div>
          ))}
        </div>

        <div className="composer">
          <textarea value={input} onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                    placeholder="输入任务…（Enter 发送，Shift+Enter 换行）" rows={2} />
          <div className="composer-actions">
            <span className="status-pill" data-state={active?.state ?? "idle"}>
              {active?.state ?? "待命"} · {specialist}
            </span>
            {active?.state === "running"
              ? <button className="stop" onClick={cancel}>■ 停止</button>
              : <button className="send" onClick={send} disabled={!ready || !input.trim()}>发送 →</button>}
          </div>
        </div>
      </main>
    </div>
  );
}
