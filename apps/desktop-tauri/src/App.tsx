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
import { ToolDock } from "./components/ToolDock";
import { ProjectPanel } from "./components/ProjectPanel";
import { Artifacts, Changes } from "./components/FileChanges";
import { shrinkWindow, restoreWindow } from "./lib/capsuleWindow";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { WindowControls } from "./components/WindowControls";
import { CommsPage } from "./components/CommsPage";
import { GalaxyPage } from "./components/GalaxyPage";
import { BoundaryPage } from "./components/BoundaryPage";
import { McpPage } from "./components/McpPage";
import { SkillPage } from "./components/SkillPage";
import { ModalConfirm, ModalInput } from "./components/Dialog";
import { MessageActions } from "./components/MessageActions";
import { open as openFile, save as saveFile } from "@tauri-apps/plugin-dialog";
import type { AttachmentInfo, RuntimeMsg, SnapshotMsg, ThinkingRecord, PermissionLevel } from "./types/ipc";

const newId = (p: string) => `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;

const messageClock = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

function MessageTime({ at }: { at?: string | number }) {
  if (at === undefined) return null;
  const date = new Date(at);
  if (!Number.isFinite(date.getTime())) return null;
  return <time className="run-time" dateTime={date.toISOString()}
               title={date.toLocaleString("zh-CN")}>{messageClock.format(date)}</time>;
}

function UserMessage({ text, at, idx, onCopy, onShare, onEdit, onRetract, onFeedback }: {
  text: string; at?: string | number; idx?: number;
  onCopy: (text: string) => void; onShare: (text: string) => void;
  onEdit?: (index: number, text: string) => void;
  onRetract?: (index: number) => void;
  onFeedback: (kind: string, text: string) => void;
}) {
  return <div className="user-turn">
    <MessageTime at={at} />
    <div className="user-msg">{text}</div>
    <MessageActions role="user" onCopy={() => onCopy(text)} onShare={() => onShare(text)}
      onEdit={onEdit ? () => onEdit(idx ?? -1, text) : undefined}
      onRetract={onRetract && idx !== undefined ? () => onRetract(idx) : undefined}
      onFeedback={(kind) => onFeedback(kind, text)} />
  </div>;
}

/** 旧端 _clean_final_text 已在 runtime 完成；这里只兜底空文本。 */
/** 历史消息：带可展开的 thinking（从 YoAi 侧持久化记录按提问文本对齐）。 */
function HistoryRun({ text, thinking, at, idx, onCopy, onShare, onRegenerate, onFeedback }: {
  text: string; thinking?: ThinkingRecord; at?: string; idx?: number;
  onCopy: (text: string) => void; onShare: (text: string) => void;
  onRegenerate: (index: number, text: string) => void;
  onFeedback: (kind: string, text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <article className="chat-run history-run">
      <header className="run-head"><span className="who">YoAi</span><MessageTime at={at} /></header>
      {thinking?.text?.trim() && (
        <div className="history-think">
          <button className="think-link" onClick={() => setOpen((v) => !v)}>
            {open ? "▾ 收起思考过程" : `▸ 查看思考过程（${thinking.text.length} 字）`}
          </button>
          {open && <div className="think-block">[思考] {thinking.text}</div>}
        </div>
      )}
      <div className="final-answer"><Markdown text={text} /></div>
      <MessageActions role="assistant" onCopy={() => onCopy(text)} onShare={() => onShare(text)}
        onRegenerate={idx === undefined ? undefined : () => onRegenerate(idx, text)}
        onFeedback={(kind) => onFeedback(kind, text)} />
    </article>
  );
}

function ChatRun({ run, streaming, onApproval, onCopy, onShare, onRegenerate, onFeedback }: {
  run: RunState; streaming: boolean; onApproval: (runId: string, allow: boolean) => void;
  onCopy: (text: string) => void; onShare: (text: string) => void;
  onRegenerate: (index: number, text: string) => void;
  onFeedback: (kind: string, text: string) => void;
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
        <MessageTime at={run.endedAt ?? run.startedAt} />
      </header>

      <ProcessPanel events={run.events} thinking={run.thinking} />

      {/* 产物（新建文件）与文件改动（+X/-Y，可开展行级 diff）*/}
      <Artifacts records={run.fileChanges.filter((c) => c.action === "create")} />
      <Changes records={run.fileChanges.filter((c) => c.action === "patch")} />

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
      {!streaming && run.finalText && (
        <MessageActions role="assistant" onCopy={() => onCopy(run.finalText)}
          onShare={() => onShare(run.finalText)}
          onRegenerate={() => onRegenerate(-1, run.input)}
          onFeedback={(kind) => onFeedback(kind, run.input)} />
      )}

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
  const [attachments, setAttachments] = useState<AttachmentInfo[]>([]);
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState("");
  const [floating, setFloating] = useState(false);
  const savedWindow = useRef<Awaited<ReturnType<typeof shrinkWindow>> | null>(null);
  const changingWindow = useRef(false);
  const [page, setPage] = useState<"chat" | "comms" | "galaxy" | "boundary" | "mcp" | "skill">("chat");
  const [snap, setSnap] = useState<SnapshotMsg | null>(null);
  const [permission, setPermission] = useState<{
    level: PermissionLevel; description: string;
  }>({ level: "smart", description: "" });
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [dialog, setDialog] = useState<
    | { kind: "rename"; sessionId: string; initial: string }
    | { kind: "delete"; sessionId: string; name: string }
    | { kind: "edit"; index: number; initial: string }
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
      if (m.type === "attachment.ready") {
        setAttachments((prev) => [...prev, m.attachment]);
      }
      if (m.type === "message.updated") {
        setErr(m.kind === "retract" ? "已撤回该提问及其回答" :
          m.kind === "edit" ? "已按编辑内容重新生成" : "已重新生成回答");
      }
      if (m.type === "share.exported") {
        setErr(`已导出到 ${m.path}`);
      }
      if (m.type === "error" && ["file", "message", "share", "browser"].includes(m.stage)) {
        setErr(m.message);
      }
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
    const attachmentBlock = attachments.map((a) =>
      `[附件：${a.name}]\n${a.content.trim() || "(二进制附件，已登记到本地，内容未抽取)"}`
    ).join("\n\n");
    const finalInput = attachmentBlock ? `${text}\n\n${attachmentBlock}` : text;
    const taskId = newId("t"); const runId = newId("r");
    beginRun(taskId, runId, finalInput);
    setMsgs([]);   // 事件数组有界：新一轮从零开始（run 视图保留，历史由 snapshot 承担）
    stickBottomRef.current = true;
    requestAnimationFrame(() => scrollToBottom(true));   // 发消息跳到底部
    void ipc.startTask(taskId, runId, finalInput).catch((e) => setErr(String(e)));
    setInput("");
    setAttachments([]);
  }, [input, ready, beginRun, scrollToBottom]);

  // 流式 token 到达时跟随底部（用户在顶部看历史时不打扰）
  const streamTick = [...runs.values()].map((r) =>
    `${r.state}:${[...r.streamText.values()].reduce((n, t) => n + t.length, 0)}:${r.finalText.length}`).join("|");
  useEffect(() => { requestAnimationFrame(() => scrollToBottom()); }, [streamTick, scrollToBottom]);

  const cancel = useCallback(() => {
    const run = runs.get(activeRunId);
    if (run) void ipc.cancelTask(run.taskId, run.runId).catch((e) => setErr(String(e)));
  }, [runs, activeRunId]);

  // 终端面板的命令走普通任务链：shell_run 仍由权限档位决定是否弹审批，
  // 终端方格本身不绕过安全机制，只负责提交与展示结果。
  const runTerminalCommand = useCallback((input: string) => {
    const taskId = newId("t"); const runId = newId("r");
    beginRun(taskId, runId, input);
    stickBottomRef.current = true;
    void ipc.startTask(taskId, runId, input).catch((e) => setErr(String(e)));
    return runId;
  }, [beginRun]);

  // ---- 消息常规操作：复制 / 分享 / 附件 / 撤回 / 编辑 / 重新生成 ----
  // RSI R0：用户动作只作为反馈信号落盘，不触发任何自动进化
  const recordFeedback = useCallback((kind: string, text: string) => {
    void ipc.recordFeedback(kind, text, "").catch((e) => setErr(String(e)));
  }, []);

  const copyText = useCallback(async (text: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text; document.body.appendChild(area); area.select();
        document.execCommand("copy"); area.remove();
      }
      setErr("已复制到剪贴板");
    } catch (e) { setErr(`复制失败：${String(e)}`); }
  }, []);

  const exportText = useCallback(async (text: string, count: number, defaultName: string) => {
    try {
      const picked = await saveFile({
        defaultPath: defaultName,
        filters: [{ name: "Markdown", extensions: ["md"] }, { name: "HTML", extensions: ["html"] }],
      });
      if (!picked) return;
      const path = String(picked);
      const payload = path.toLowerCase().endsWith(".html")
        ? `<!doctype html><meta charset="utf-8"><title>YoAi 分享</title><pre>${text
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre>`
        : text;
      await ipc.shareExport(path, payload, count);
    } catch (e) { setErr(`导出失败：${String(e)}`); }
  }, []);

  const shareSingle = useCallback((text: string) => {
    void exportText(`# YoAi 消息\n\n${text}`, 1, "yoai-message.md");
  }, [exportText]);
  const shareConversation = useCallback(() => {
    const lines = (snap?.history ?? []).map((h) =>
      `**${h.role === "user" ? "我" : "YoAi"}**：\n\n${h.text}`);
    void exportText(lines.join("\n\n---\n\n"), lines.length, "yoai-conversation.md");
  }, [snap, exportText]);

  const pickAttachment = useCallback(async () => {
    try {
      const picked = await openFile({
        multiple: false, title: "选择附件",
        filters: [{ name: "常用文件", extensions: ["txt", "md", "py", "js", "ts", "json", "csv", "html", "css", "yml", "yaml", "toml", "log", "pdf", "png", "jpg", "jpeg", "gif"] }],
      });
      if (picked && typeof picked === "string") await ipc.prepareAttachment(picked);
    } catch (e) { setErr(`添加附件失败：${String(e)}`); }
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
    void ipc.removeAttachment(id).catch((e) => setErr(String(e)));
  }, []);

  const startEdit = useCallback((index: number, initial: string) => {
    setDialog({ kind: "edit", index, initial });
  }, []);

  const retract = useCallback((index: number) => {
    void ipc.retractMessage(index).catch((e) => setErr(String(e)));
  }, []);

  const regenerate = useCallback((index: number, input: string) => {
    const taskId = newId("t"); const runId = newId("r");
    beginRun(taskId, runId, input);
    void ipc.regenerate(index, input, taskId, runId).catch((e) => setErr(String(e)));
  }, [beginRun]);

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
        <button className={`nav-item ${page === "boundary" ? "active" : ""}`} title="能力边界看板" aria-current={page === "boundary" ? "page" : undefined}
                onClick={() => setPage("boundary")}>边界</button>
        <button className={`nav-item ${page === "mcp" ? "active" : ""}`} title="MCP 扩展" aria-current={page === "mcp" ? "page" : undefined}
                onClick={() => setPage("mcp")}>MCP</button>
        <button className={`nav-item ${page === "skill" ? "active" : ""}`} title="技能包" aria-current={page === "skill" ? "page" : undefined}
                onClick={() => setPage("skill")}>技能</button>
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
                  if (h.role === "user") return <UserMessage key={`h${i}`} text={h.text} at={h.at}
                    idx={h.idx} onCopy={copyText} onShare={shareSingle}
                    onEdit={startEdit} onRetract={retract} onFeedback={recordFeedback} />;
                  // 对齐 thinking：找最近一条用户提问匹配该记录的 input
                  const prevUser = [...arr.slice(0, i)].reverse().find((m) => m.role === "user");
                  const think = (snap?.thinking_log ?? []).find(
                    (t) => t.input && prevUser && t.input.trim() === prevUser.text.trim());
                  return <HistoryRun key={`h${i}`} text={h.text} thinking={think} at={h.at}
                    idx={h.idx} onCopy={copyText} onShare={shareSingle} onRegenerate={regenerate}
                    onFeedback={recordFeedback} />;
                })}
                {runList.length === 0 && (snap?.history ?? []).length === 0 && (
                  <div className="empty">输入一个任务，开始与 YoAi 对话。</div>
                )}
                {runList.map((run) => (
                  <div key={run.runId}>
                    <UserMessage text={run.input} at={run.startedAt}
                      onCopy={copyText} onShare={shareSingle}
                      onEdit={startEdit} onFeedback={recordFeedback} />
                    <ChatRun run={run} streaming={run.runId === activeRunId}
                             onCopy={copyText} onShare={shareSingle} onRegenerate={regenerate}
                             onFeedback={recordFeedback}
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
                  <button type="button" className="attach-btn" title="添加附件"
                          onClick={() => void pickAttachment()}>＋ 附件</button>
                  <button type="button" className="attach-btn" title="导出当前会话"
                          onClick={shareConversation}>分享会话</button>
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
                {attachments.length > 0 && (
                  <div className="attachment-chips">
                    {attachments.map((a) => (
                      <span key={a.id} className="attachment-chip" title={a.path}>
                        📎 {a.name}
                        <button type="button" aria-label={`移除附件 ${a.name}`}
                                onClick={() => removeAttachment(a.id)}>×</button>
                      </span>
                    ))}
                  </div>
                )}
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
            <div className="right-rail">
              <ToolDock snap={snap} runs={runs} ready={ready} onRunCommand={runTerminalCommand} onError={setErr} />
            </div>
          </main>
        )}

        {page === "comms" && <CommsPage />}
        {page === "galaxy" && <GalaxyPage />}
        {page === "boundary" && <BoundaryPage />}
        {page === "mcp" && <McpPage />}
        {page === "skill" && <SkillPage />}
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
      {dialog?.kind === "edit" && (
        <ModalInput title="编辑提问" placeholder="修改后的提问" initial={dialog.initial}
                    onCancel={() => setDialog(null)}
                    onOk={(text) => {
                      if (!text.trim()) return;
                      const taskId = newId("t"); const runId = newId("r");
                      beginRun(taskId, runId, text);
                      void ipc.editMessage(dialog.index, text, taskId, runId)
                        .catch((e) => setErr(String(e)));
                      setDialog(null);
                    }} />
      )}
    </div>
  );
}
