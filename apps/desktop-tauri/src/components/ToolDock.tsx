/** 右侧工具方格：浏览器 / 终端 / 查看文件。
 *
 * 设计边界：
 * - 浏览器：iframe 内嵌 + 系统浏览器兜底（站点禁止内嵌时）；runtime 只校验 http/https。
 * - 终端：不绕过权限——命令作为普通任务交给 YoAi 调 shell_run，审批仍走对话区；
 *   面板只负责提交命令、展示该 run 的 tool_result。
 * - 查看文件：runtime 只读 fs.list/fs.read，路径限制在项目根或工作区内。
 */

import { useEffect, useMemo, useState } from "react";
import { ipc } from "../lib/ipc";
import type { FileEntry, RuntimeMsg } from "../types/ipc";
import type { RunState } from "../hooks/useTaskStream";

type Tool = "browser" | "terminal" | "files";

interface TerminalEntry {
  runId: string;
  command: string;
}

interface Props {
  runs: Map<string, RunState>;
  ready: boolean;
  onRunCommand: (command: string) => string;
  onError?: (message: string) => void;
}

const TERMINAL_HINT = "请在当前工作区用 shell_run 执行下面这条命令，并把命令输出原样报告（不要改写）：\n";

function formatResult(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function safeUrl(raw: string): string | null {
  try {
    const url = new URL(raw.trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export function ToolDock({ runs, ready, onRunCommand, onError }: Props) {
  const [open, setOpen] = useState<Tool | null>(null);
  const [notice, setNotice] = useState("");

  // 浏览器
  const [urlDraft, setUrlDraft] = useState("");
  const [url, setUrl] = useState("");
  const [frameKey, setFrameKey] = useState(0);

  // 终端
  const [command, setCommand] = useState("");
  const [terminal, setTerminal] = useState<TerminalEntry[]>([]);

  // 查看文件
  const [root, setRoot] = useState("");
  const [label, setLabel] = useState("工作区");
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [content, setContent] = useState<{ path: string; text: string; truncated: boolean } | null>(null);

  useEffect(() => {
    const off = ipc.onMessage((msg: RuntimeMsg) => {
      if (msg.type === "file.tree") {
        setRoot(msg.root);
        setLabel(msg.label);
        setPath(msg.path);
        setEntries(msg.entries);
      } else if (msg.type === "file.content") {
        setContent({ path: msg.path, text: msg.content, truncated: msg.truncated });
      } else if (msg.type === "browser.opened") {
        setNotice(`已在系统浏览器打开 ${msg.url}`);
      } else if (msg.type === "error" && (msg.stage === "file" || msg.stage === "browser")) {
        setNotice(msg.message);
        onError?.(msg.message);
      }
    });
    return off;
  }, [onError]);

  useEffect(() => {
    if (open === "files" && ready) void ipc.listFiles(path).catch((e) => setNotice(String(e)));
    // path 变化由用户点击驱动，这里只在面板首次打开时拉一次根目录
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ready]);

  const terminalLines = useMemo(() => terminal.map((entry) => {
    const run = runs.get(entry.runId);
    const results = (run?.events ?? [])
      .filter((e) => e.name === "tool_result" && String(e.data.tool ?? "").includes("shell_run"))
      .map((e) => formatResult(e.data.result))
      .join("\n");
    const errors = (run?.events ?? [])
      .filter((e) => e.name === "error" || e.name === "permission_denied" || e.name === "budget_exceeded")
      .map((e) => String(e.data.error ?? e.data.reason ?? e.data.message ?? "执行出错"))
      .join("\n");
    return { ...entry, state: run?.state ?? "queued", output: results || errors };
  }), [terminal, runs]);

  function submitCommand() {
    const text = command.trim();
    if (!text || !ready) return;
    const runId = onRunCommand(TERMINAL_HINT + text);
    setTerminal((prev) => [...prev.slice(-19), { runId, command: text }]);
    setCommand("");
    setNotice("已提交给 YoAi；如需审批请在对话区确认。");
  }

  function goPath(next: string) {
    setContent(null);
    setPath(next);
    void ipc.listFiles(next).catch((e) => setNotice(String(e)));
  }

  const crumbs = path ? path.split("/").filter(Boolean) : [];

  return (
    <div className="tool-dock">
      <div className="tool-dock-grid" aria-label="内置工具">
        <button type="button" className={`dock-tile ${open === "browser" ? "active" : ""}`}
                aria-expanded={open === "browser"} onClick={() => setOpen(open === "browser" ? null : "browser")}>
          <span className="dock-icon">◎</span><span>浏览器</span>
        </button>
        <button type="button" className={`dock-tile ${open === "terminal" ? "active" : ""}`}
                aria-expanded={open === "terminal"} onClick={() => setOpen(open === "terminal" ? null : "terminal")}>
          <span className="dock-icon">›_</span><span>终端</span>
        </button>
        <button type="button" className={`dock-tile ${open === "files" ? "active" : ""}`}
                aria-expanded={open === "files"} onClick={() => setOpen(open === "files" ? null : "files")}>
          <span className="dock-icon">▤</span><span>查看文件</span>
        </button>
      </div>

      {open && (
        <section className="tool-panel" aria-label={{ browser: "内置浏览器", terminal: "终端", files: "查看文件" }[open]}>
          <header>
            <strong>{{ browser: "内置浏览器", terminal: "终端", files: "查看文件" }[open]}</strong>
            <button type="button" className="tool-panel-close" aria-label="关闭" onClick={() => setOpen(null)}>×</button>
          </header>

          {notice && <div className="tool-notice">{notice}</div>}

          {open === "browser" && (
            <div className="tool-browser">
              <div className="tool-urlbar">
                <input value={urlDraft} onChange={(e) => setUrlDraft(e.target.value)}
                       onKeyDown={(e) => {
                         if (e.key !== "Enter") return;
                         const next = safeUrl(urlDraft);
                         if (next) { setUrl(next); setFrameKey((n) => n + 1); }
                         else setNotice("请输入 http:// 或 https:// 开头的网址");
                       }}
                       placeholder="https://…" aria-label="网址" />
                <button type="button" onClick={() => {
                  const next = safeUrl(urlDraft);
                  if (next) { setUrl(next); setFrameKey((n) => n + 1); }
                  else setNotice("请输入 http:// 或 https:// 开头的网址");
                }}>打开</button>
                <button type="button" disabled={!url}
                        onClick={() => void ipc.openExternal(url).catch((e) => setNotice(String(e)))}>
                  系统打开
                </button>
              </div>
              {url
                ? <iframe key={frameKey} src={url} title="内置浏览器" className="tool-frame"
                          sandbox="allow-scripts allow-same-origin allow-forms allow-popups" />
                : <div className="tool-empty">输入网址后在这里打开。部分站点禁止内嵌，请用「系统打开」。</div>}
            </div>
          )}

          {open === "terminal" && (
            <div className="tool-terminal">
              <div className="tool-urlbar">
                <input value={command} onChange={(e) => setCommand(e.target.value)}
                       onKeyDown={(e) => { if (e.key === "Enter") submitCommand(); }}
                       placeholder="要执行的命令（仍走审批）" aria-label="命令" />
                <button type="button" disabled={!ready || !command.trim()} onClick={submitCommand}>执行</button>
              </div>
              <div className="tool-log">
                {terminalLines.length === 0 && <div className="tool-empty">命令通过对话区审批后执行，输出会显示在这里。</div>}
                {terminalLines.map((entry) => (
                  <div key={entry.runId} className="tool-log-entry">
                    <div className="tool-log-head">$ {entry.command} <span data-state={entry.state}>{entry.state}</span></div>
                    <pre>{entry.output || "等待执行结果…"}</pre>
                  </div>
                ))}
              </div>
            </div>
          )}

          {open === "files" && (
            <div className="tool-files">
              <div className="tool-pathbar">
                <button type="button" title={root || "当前文件根目录"} onClick={() => goPath("")}>{label}</button>
                {crumbs.map((part, i) => (
                  <span key={`${part}-${i}`}>
                    <span className="tool-sep">/</span>
                    <button type="button" onClick={() => goPath(crumbs.slice(0, i + 1).join("/"))}>{part}</button>
                  </span>
                ))}
              </div>
              <div className="tool-tree">
                {entries.length === 0 && <div className="tool-empty">这个目录是空的。</div>}
                {entries.map((entry) => (
                  <button type="button" key={entry.path} className="tool-entry"
                          onClick={() => {
                            if (entry.is_dir) goPath(entry.path);
                            else {
                              setContent(null);
                              void ipc.readFile(entry.path).catch((e) => setNotice(String(e)));
                            }
                          }}>
                    <span className="tool-entry-icon">{entry.is_dir ? "▸" : "·"}</span>{entry.name}
                  </button>
                ))}
              </div>
              {content && (
                <div className="tool-file-content">
                  <div className="tool-file-head">{content.path}{content.truncated ? " · 仅预览前 20 万字符" : ""}</div>
                  <pre>{content.text}</pre>
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
