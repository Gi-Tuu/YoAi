/** YoAi 下一代桌面工作台（Tauri + React）。
 *  完整对齐旧 PySide6 端能力：会话管理（切换/新建/重命名/删除）、
 *  个人事实/长期目标/本轮记忆侧栏、错误可见（部分失败）、
 *  模型 chip、纸墨主题切换、通讯页、星球系页。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ipc } from "./lib/ipc";
import { useTaskStream, type RunState } from "./hooks/useTaskStream";
import { ProcessPanel } from "./components/ProcessPanel";
import { Markdown } from "./components/Markdown";
import { SideCards } from "./components/SideCards";
import { ProjectPanel } from "./components/ProjectPanel";
import { shrinkWindow, restoreWindow } from "./lib/capsuleWindow";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { WindowControls } from "./components/WindowControls";
import { CommsPage } from "./components/CommsPage";
import { GalaxyPage } from "./components/GalaxyPage";
import { ModalConfirm, ModalInput } from "./components/Dialog";
import type { RuntimeMsg, SnapshotMsg, ThinkingRecord, PermissionLevel } from "./types/ipc";

const newId = (p: string) => `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;

/** 旧端 _clean_final_text 已在 runtime 完成；这里只兜底空文本。 */
/** 历史消息：带可展开的 thinking（从 YoAi 侧持久化记录按提问文本对齐）。 */
function HistoryRun({ text, thinking }: { text: string; thinking?: ThinkingRecord }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="chat-run history-run">
      <header className="run-head"><span className="who">YoAi</span></header>
      {thinking?.text?.trim() && (
        <div className="history-think">
          <button className="think-link" onClick={() => setOpen((v) => !v)}>
            {open ? "▾ 收起思考过程" : `▸ 查看思考过程（${thinking.text.length} 字）`}
          </button>
          {open && <div className="think-block">[思考] {thinking.text}</div>}
        </div>
      )}
      <div className="final-answer"><Markdown text={text} /></div>
    </article>
  );
}

function ChatRun({ run, streaming, onApproval }: {
  run: RunState; streaming: boolean; onApproval: (runId: string, allow: boolean) => void;
}) {
  const rounds = useMemo(() => [...run.streamText.entries()].sort((a, b) => a[0] - b[0]), [run.streamText]);
  // 静默失败修复（对齐旧端 _task_had_error）：报错后的"完成"必须标出来
  const hadError = run.events.some((e) =>
    e.name === "error" || e.name === "permission_denied" || e.name === "budget_exceeded");
  const stateText = run.state === "done" && hadError ? "部分失败" : run.state;

  return (
    <article className="chat-run">
      <header className="run-head">
        <span className="who">YoAi</span>
        <span className="state" data-state={hadError && run.state === "done" ? "failed" : run.state}>
          {stateText}
        </span>
        <span className="run-time">{new Date(run.startedAt).toLocaleTimeString("zh-CN")}</span>
      </header>

      <ProcessPanel events={run.events} thinking={run.thinking} />

      {/* 错误必须进正文（旧端静默失败修复语义） */}
      {run.events.filter((e) => e.name === "error" || e.name === "permission_denied" || e.name === "budget_exceeded")
        .map((e) => (
          <div key={`err-${e.seq}`} className="run-error">
            ⚠️ {String(e.data.error ?? e.data.reason ?? e.data.message ?? "执行出错")}
          </div>
        ))}

      {/* 流式文本：每轮一段；final 到了就隐藏，只留定稿，避免同一段显示两遍 */}
      {streaming && !run.finalText && rounds.map(([round, text]) => text && (
        <div key={round} className="stream-block"><Markdown text={text} streaming /></div>
      ))}

      {run.finalText && <div className="final-answer"><Markdown text={run.finalText} /></div>}

      {run.approval && (
        <div className="approval-box">
          <p>{run.approval.question} <code>{run.approval.tool}</code></p>
          {run.approval.detail && <pre className="approval-detail">{run.approval.detail}</pre>}
          <div>
            <button onClick={() => onApproval(run.runId, true)}>允许执行</button>
            <button onClick={() => onApproval(run.runId, false)}>拒绝</button>
          </div>
        </div>
      )}
    </article>
  );
}

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("yoai-theme") as "light" | "dark") || "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("yoai-theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "light" ? "dark" : "light"))] as const;
}

export default function App() {
  const [msgs, setMsgs] = useState<RuntimeMsg[]>([]);
  const [input, setInput] = useState("");
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState("");
  const [floating, setFloating] = useState(false);
  const savedWindow = useRef<Awaited<ReturnType<typeof shrinkWindow>> | null>(null);
  const changingWindow = useRef(false);
  const [page, setPage] = useState<"chat" | "comms" | "galaxy">("chat");
  const [snap, setSnap] = useState<SnapshotMsg | null>(null);
  const [permission, setPermission] = useState<{
    level: PermissionLevel; description: string;
  }>({ level: "smart", description: "" });
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [dialog, setDialog] = useState<
    | { kind: "rename"; sessionId: string; initial: string }
    | { kind: "delete"; sessionId: string; name: string }
    | null
  >(null);
  const [theme, toggleTheme] = useTheme();
  const { runs, activeRunId, beginRun, clearApproval, resetRuns } = useTaskStream(msgs);
  // 快照增量消费 + 会话切换检测
  const procRef = useRef(0);
  const currentIdRef = useRef("");
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const stickBottomRef = useRef(true);   // 用户是否在底部（主动上滚则暂停自动跟随）

  // 滚动跟随：内容变化/切会话/发消息时滚底；用户主动上滚时不打扰
  const scrollToBottom = useCallback((force = false) => {
    const el = chatScrollRef.current;
    if (!el || (!force && !stickBottomRef.current)) return;
    el.scrollTop = el.scrollHeight;
    stickBottomRef.current = true;
  }, []);
  const onChatScroll = useCallback(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    stickBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }, []);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      setMsgs((prev) => [...prev, m]);   // 所有 runtime 消息进入消费队列
      if (m.type === "ready") setReady(true);
      if (m.type === "error" && (m.stage === "startup" || (m.stage === "protocol" && !m.run_id))) setErr(m.message);
      if (m.type === "permission.state") {
        setPermission({ level: m.level, description: m.description });
      }
    });
    void ipc.connect().catch((e) => setErr(String(e)));
    return () => { off(); void ipc.shutdown().catch(() => {}); };
  }, []);

  // snapshot：更新会话/侧栏数据；current_id 变化时清空 run 视图
  useEffect(() => {
    if (msgs.length < procRef.current) procRef.current = 0;
    const batch = msgs.slice(procRef.current);
    procRef.current = msgs.length;
    for (const m of batch) {
      if (m.type !== "snapshot") continue;
      if (m.current_id !== currentIdRef.current) {
        currentIdRef.current = m.current_id;
        resetRuns();
        stickBottomRef.current = true;
        requestAnimationFrame(() => scrollToBottom(true));  // 切会话回到最新消息
      }
      setSnap(m);
      requestAnimationFrame(() => scrollToBottom());
    }
  }, [msgs, resetRuns]);

  const send = useCallback(() => {
    const text = input.trim();
    if (!text || !ready) return;
    const taskId = newId("t"); const runId = newId("r");
    beginRun(taskId, runId, text);
    setMsgs([]);   // 事件数组有界：新一轮从零开始（run 视图保留，历史由 snapshot 承担）
    stickBottomRef.current = true;
    requestAnimationFrame(() => scrollToBottom(true));   // 发消息跳到底部
    void ipc.startTask(taskId, runId, text).catch((e) => setErr(String(e)));
    setInput("");
  }, [input, ready, beginRun, scrollToBottom]);

  // 流式 token 到达时跟随底部（用户在顶部看历史时不打扰）
  const streamTick = [...runs.values()].map((r) =>
    `${r.state}:${[...r.streamText.values()].reduce((n, t) => n + t.length, 0)}:${r.finalText.length}`).join("|");
  useEffect(() => { requestAnimationFrame(() => scrollToBottom()); }, [streamTick, scrollToBottom]);

  const cancel = useCallback(() => {
    const run = runs.get(activeRunId);
    if (run) void ipc.cancelTask(run.taskId, run.runId).catch((e) => setErr(String(e)));
  }, [runs, activeRunId]);

  const active = runs.get(activeRunId);
  const busy = active?.state === "running";
  const usage = snap?.context_usage;
  const used = usage ? Math.min(usage.limit, usage.used + Array.from(input).length) : 0;
  const percent = usage ? Math.round(100 * used / usage.limit) : 0;
  const contextLabel = usage ? `历史与草稿约 ${used.toLocaleString()} / ${usage.limit.toLocaleString()} 字符（${percent}%）` : "正在读取上下文";
  const modelOptions = snap?.model_options ?? [];
  const runList = useMemo(() => [...runs.values()], [runs]);
  const sessions = snap?.sessions ?? [];

  const sessionLabel = useCallback((s: { name: string; created_at?: string }) => {
    if (!s.created_at) return s.name;
    const d = new Date(s.created_at);
    if (Number.isNaN(d.getTime())) return s.name;
    return `${s.name} · ${String(d.getMonth() + 1).padStart(2, "0")}月${String(d.getDate()).padStart(2, "0")}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }, []);

  const setCapsuleMode = useCallback(async (enabled: boolean) => {
    if (changingWindow.current) return;
    changingWindow.current = true;
    try {
      setErr("");
      if (enabled) {
        savedWindow.current = await shrinkWindow();
      } else if (savedWindow.current) {
        await restoreWindow(savedWindow.current);
        savedWindow.current = null;
      }
      setFloating(enabled);
    } catch (error) {
      setErr(`窗口切换失败：${String(error)}`);
    } finally {
      changingWindow.current = false;
    }
  }, []);

  const awaitingApproval = runList.some((run) => run.approval);
  useEffect(() => {
    if (floating && awaitingApproval) void setCapsuleMode(false);
  }, [awaitingApproval, floating, setCapsuleMode]);

  if (floating) {
    const labels = { running: "执行中", done: "已完成", failed: "执行失败", cancelled: "已取消" };
    const state = active?.state ?? "idle";
    const label = state in labels ? labels[state as keyof typeof labels] : "待命";
    return (
      <div className="capsule" title={err || undefined}>
        <div className="capsule-handle" title="拖动悬浮窗口" aria-hidden="true"
             onMouseDown={(event) => {
               if (event.button === 0) void getCurrentWindow().startDragging().catch((error) => setErr(String(error)));
             }}>⠿</div>
        <button className="capsule-expand" onClick={() => void setCapsuleMode(false)}
                title="恢复主窗口" aria-label="恢复主窗口">
          <span className="capsule-dot" data-state={state} />
          <span>{err ? "恢复失败，点击重试" : `YoAi · ${label}`}</span>
          {active && !err && <span className="capsule-steps">{active.events.length} 步</span>}
        </button>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <nav className="nav-rail">
        <div className="session-nav"
             onPointerEnter={(event) => { if (event.pointerType !== "touch") setSessionsOpen(true); }}
             onPointerLeave={(event) => { if (event.pointerType !== "touch") setSessionsOpen(false); }}
             onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setSessionsOpen(false); }}
             onKeyDown={(event) => {
               if (event.key === "Escape" && sessionsOpen) {
                 event.currentTarget.querySelector("button")?.focus();
                 setSessionsOpen(false);
               }
             }}>
          <button className={`nav-item ${page === "chat" ? "active" : ""}`} title="我的对话" aria-current={page === "chat" ? "page" : undefined}
                  aria-expanded={sessionsOpen} aria-controls="session-list-panel"
                  onClick={() => { setPage("chat"); setSessionsOpen(true); }}>对话</button>
          {sessionsOpen && (
            <section id="session-list-panel" className="session-flyout" aria-label="会话">
              <header>
                <strong>会话</strong>
                <button disabled={!ready || busy} onClick={() => {
                  void ipc.createSession("新会话").catch((error) => setErr(String(error)));
                  setPage("chat"); setSessionsOpen(false);
                }}>＋ 新建</button>
              </header>
              <ul className="session-list">
                {sessions.length === 0 && <li className="session-empty">暂无会话</li>}
                {sessions.map((session) => (
                  <li key={session.id}>
                    <button className="session-pick" title={sessionLabel(session)}
                            aria-current={session.id === snap?.current_id ? "true" : undefined}
                            disabled={busy} onClick={() => {
                              void ipc.switchSession(session.id).catch((error) => setErr(String(error)));
                              setPage("chat"); setSessionsOpen(false);
                            }}>{sessionLabel(session)}</button>
                    <button className="session-icon ghost" title="重命名"
                            aria-label={`重命名 ${session.name}`} disabled={busy} onClick={() => {
                              setSessionsOpen(false);
                              setDialog({ kind: "rename", sessionId: session.id, initial: session.name });
                            }}>✎</button>
                    <button className="session-icon ghost" title="删除"
                            aria-label={`删除 ${session.name}`} disabled={busy} onClick={() => {
                              setSessionsOpen(false);
                              setDialog({ kind: "delete", sessionId: session.id, name: session.name });
                            }}>🗑︎</button>
                  </li>
                ))}
              </ul>
              <ProjectPanel
                projects={snap?.projects ?? []}
                sessions={sessions}
                currentSessionId={snap?.current_id ?? ""}
                ready={ready} busy={busy}
                onError={(message) => setErr(message)} />
            </section>
          )}
        </div>
        <button className={`nav-item ${page === "comms" ? "active" : ""}`} title="通讯" aria-current={page === "comms" ? "page" : undefined}
                onClick={() => setPage("comms")}>通讯</button>
        <button className={`nav-item ${page === "galaxy" ? "active" : ""}`} title="星球系" aria-current={page === "galaxy" ? "page" : undefined}
                onClick={() => setPage("galaxy")}>星球</button>
        <div className="nav-spacer" />
        <button className="nav-item ghost" title="切换纸墨主题" onClick={toggleTheme}>
          {theme === "light" ? "墨" : "纸"}
        </button>
        <button className="nav-item ghost" title="切换悬浮模式" disabled={awaitingApproval} onClick={() => void setCapsuleMode(true)}>◱</button>
      </nav>

      <div className="main-col">
        <div className="window-drag-strip" data-tauri-drag-region aria-hidden="true" />
        <WindowControls onError={setErr} />

        {err && <div className="error-bar">⚠ {err}</div>}
        {!ready && <div className="boot-bar">正在连接 Python Runtime…</div>}

        {page === "chat" && (
          <main className="chat-layout">
            <div className="chat-col">
              <div className="chat-scroll" ref={chatScrollRef} onScroll={onChatScroll}>
                {/* 历史消息（当前会话持久化历史） */}
                {(snap?.history ?? []).map((h, i, arr) => {
                  if (h.role === "user") return <div key={`h${i}`} className="user-msg">{h.text}</div>;
                  // 对齐 thinking：找最近一条用户提问匹配该记录的 input
                  const prevUser = [...arr.slice(0, i)].reverse().find((m) => m.role === "user");
                  const think = (snap?.thinking_log ?? []).find(
                    (t) => t.input && prevUser && t.input.trim() === prevUser.text.trim());
                  return <HistoryRun key={`h${i}`} text={h.text} thinking={think} />;
                })}
                {runList.length === 0 && (snap?.history ?? []).length === 0 && (
                  <div className="empty">输入一个任务，开始与 YoAi 对话。</div>
                )}
                {runList.map((run) => (
                  <div key={run.runId}>
                    <div className="user-msg">{run.input}</div>
                    <ChatRun run={run} streaming={run.runId === activeRunId}
                             onApproval={(runId, allow) => {
                               clearApproval(runId);   // 点了立即消失
                               void ipc.replyApproval(run.taskId, run.runId, allow)
                                 .catch((e) => setErr(String(e)));
                             }} />
                  </div>
                ))}
              </div>

              <div className="composer">
                <div className="composer-toolbar">
                  <label className="perm-control" title={permission.description}>
                    <span>权限</span>
                    <select value={permission.level}
                            data-level={permission.level}
                            onChange={(e) => {
                              const level = e.target.value as PermissionLevel;
                              void ipc.setPermission(level).catch((err) => setErr(String(err)));
                            }}>
                      <option value="full">允许完全访问</option>
                      <option value="smart">智能访问</option>
                      <option value="manual">手批访问</option>
                    </select>
                  </label>
                </div>
                <div className="composer-field">
                  <div className="context-model" title={`${contextLabel} · ${snap?.model ?? "模型"}`}>
                    <div className="context-track" role="meter" aria-valuemin={0} aria-valuemax={100}
                         aria-valuenow={percent} aria-label={contextLabel}>
                      <span style={{ height: percent + "%" }} />
                    </div>
                    <select aria-label="切换模型" value={snap?.model_id ?? ""}
                            disabled={!ready || busy || modelOptions.length === 0}
                            onChange={(e) => {
                              setErr("");
                              void ipc.send({ v: 1, type: "model.select", model_id: e.target.value })
                                .catch((error) => setErr(String(error)));
                            }}>
                      {modelOptions.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
                    </select>
                  </div>
                  <textarea value={input} onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
                            aria-label="输入任务" placeholder="输入任务…（Enter 发送，Shift+Enter 换行）" rows={2} />
                  {busy
                    ? <button className="stop" onClick={cancel}>■ 停止</button>
                    : <button className="send" onClick={send} disabled={!ready || !input.trim()}>发送 →</button>}
                </div>
              </div>
            </div>
            <SideCards snap={snap} />
          </main>
        )}

        {page === "comms" && <CommsPage />}
        {page === "galaxy" && <GalaxyPage />}
      </div>

      {dialog?.kind === "rename" && (
        <ModalInput title="重命名会话" placeholder="会话名称" initial={dialog.initial}
                    onCancel={() => setDialog(null)}
                    onOk={(name) => { void ipc.renameSession(dialog.sessionId, name); setDialog(null); }} />
      )}
      {dialog?.kind === "delete" && (
        <ModalConfirm title="删除会话" text={`从列表删除「${dialog.name}」？`}
                     detail="本地历史文件会保留。" okLabel="删除"
                     onCancel={() => setDialog(null)}
                     onOk={() => { void ipc.deleteSession(dialog.sessionId); setDialog(null); }} />
      )}
    </div>
  );
}
