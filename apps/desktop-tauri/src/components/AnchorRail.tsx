/** 右侧信息锚点：把常驻卡片改成边缘小方块，悬停以自身为中心展开，点击钉住成原生浮窗。
 *  对齐你 2026-11-25 的设计：开合动画从锚点生长，位置按与对话区/窗口边缘的距离自适应。 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { SnapshotMsg } from "../types/ipc";

export type PanelKind = "facts" | "goals" | "memory";

export interface RectLike { left: number; top: number; width: number; height: number; }
export interface Placement { left: number; top: number; side: "left" | "right" | "center"; }

/** 纯函数：算 popover 落点。以锚点中心为基准，与对话区重叠过半时改到空间更大的一侧，
 *  最后钳制进视口。jsdom/真机同逻辑，便于单测。 */
export function computeAnchorPosition(
  anchor: RectLike,
  panel: { width: number; height: number },
  viewport: { width: number; height: number },
  dialog: RectLike | null,
  margin = 10,
): Placement {
  const ax = anchor.left + anchor.width / 2;
  const ay = anchor.top + anchor.height / 2;
  const { width: pw, height: ph } = panel;
  let left = ax - pw / 2;
  let side: Placement["side"] = "center";

  if (dialog) {
    const overlap = Math.min(left + pw, dialog.left + dialog.width) - Math.max(left, dialog.left);
    const overlapRatio = overlap > 0 ? overlap / pw : 0;
    if (overlapRatio > 0.5) {
      const spaceRight = viewport.width - (anchor.left + anchor.width) - margin;
      const spaceLeft = anchor.left - margin;
      if (spaceRight >= spaceLeft) {
        left = anchor.left + anchor.width + 4;
        side = "right";
      } else {
        left = anchor.left - pw - 4;
        side = "left";
      }
    }
  }
  left = Math.max(margin, Math.min(left, viewport.width - pw - margin));
  let top = ay - ph / 2;
  top = Math.max(margin, Math.min(top, viewport.height - ph - margin));
  return { left, top, side };
}

const GOAL_MARKS: Record<string, string> = {
  pending: "○", active: "●", done: "✓", cancelled: "×",
};

interface PanelContentProps { snap: SnapshotMsg | null; kind: PanelKind; }

function PanelContent({ snap, kind }: PanelContentProps) {
  if (kind === "facts") {
    const facts = Object.entries(snap?.facts ?? {});
    return facts.length === 0
      ? <div className="side-empty">还没有个人事实。</div>
      : <>{facts.map(([k, v]) => (
          <div key={k} className="side-row" title={`${k} · ${v}`}>
            <span className="side-key">{k}</span><span className="side-val">{v}</span>
          </div>))}</>;
  }
  if (kind === "goals") {
    const goals = snap?.goals ?? [];
    return goals.length === 0
      ? <div className="side-empty">还没有长期目标。</div>
      : <>{goals.map((g) => (
          <div key={g.id} className="side-row" title={`状态：${g.status}\nID：${g.id}`}>
            <span className="side-mark">{GOAL_MARKS[g.status] ?? "○"}</span>
            <span className="side-val">{g.title}</span>
          </div>))}</>;
  }
  const stats = snap?.write_stats ?? {};
  const events = Number(stats.events ?? 0);
  const sources = ([["model", "模型"], ["fallback", "规则兜底"], ["supplement", "数字补充"]] as const)
    .filter(([k]) => Number(stats[k] ?? 0) > 0)
    .map(([, label]) => label);
  return <>
    <div className={events ? "mem-line" : "mem-line dim"}>
      {events ? `本轮记忆 +${events}` : "本轮未写入记忆"}
    </div>
    <div className="mem-src">时间记忆 · {sources.length ? sources.join("、") : "无新增"}</div>
  </>;
}

const PANELS: { kind: PanelKind; glyph: string; title: string }[] = [
  { kind: "facts", glyph: "事", title: "个人事实" },
  { kind: "goals", glyph: "志", title: "长期目标" },
  { kind: "memory", glyph: "忆", title: "本轮记忆" },
];

function countOf(snap: SnapshotMsg | null, kind: PanelKind): number {
  if (kind === "facts") return Object.keys(snap?.facts ?? {}).length;
  if (kind === "goals") return (snap?.goals ?? []).length;
  return Number(snap?.write_stats?.events ?? 0);
}

interface AnchorProps {
  panel: (typeof PANELS)[number];
  snap: SnapshotMsg | null;
  onPin: (kind: PanelKind, title: string) => void;
}

function Anchor({ panel, snap, onPin }: AnchorProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<Placement | null>(null);
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const closeTimer = useRef<number | null>(null);

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) return;
    const a = anchorRef.current.getBoundingClientRect();
    const p = popRef.current?.getBoundingClientRect();
    const dialog = document.querySelector(".chat-scroll")?.getBoundingClientRect() ?? null;
    setPos(computeAnchorPosition(
      { left: a.left, top: a.top, width: a.width, height: a.height },
      { width: p?.width ?? 300, height: p?.height ?? 220 },
      { width: window.innerWidth, height: window.innerHeight },
      dialog ? { left: dialog.left, top: dialog.top, width: dialog.width, height: dialog.height } : null,
    ));
  }, [open]);

  const cancelClose = () => { if (closeTimer.current !== null) { clearTimeout(closeTimer.current); closeTimer.current = null; } };
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => { setOpen(false); setPos(null); }, 140);
  };
  useEffect(() => () => cancelClose(), []);

  const count = countOf(snap, panel.kind);
  return (
    <div className="anchor-item" onMouseEnter={cancelClose} onMouseLeave={scheduleClose}>
      <button
        ref={anchorRef}
        className={`anchor-tile ${open ? "is-open" : ""}`}
        title={`${panel.title} · ${count}`}
        aria-expanded={open}
        onMouseEnter={() => { cancelClose(); setOpen(true); }}
        onFocus={() => setOpen(true)}
      >
        <span className="anchor-glyph">{panel.glyph}</span>
        {count > 0 && <span className="anchor-badge">{count}</span>}
      </button>
      {open && (
        <div
          ref={popRef}
          className={`anchor-pop ${pos ? "is-placed" : ""}`}
          data-side={pos?.side ?? "center"}
          style={pos ? { left: pos.left, top: pos.top } : { left: -9999, top: -9999 }}
          onMouseEnter={cancelClose}
        >
          <header className="anchor-pop-head">
            <span>{panel.title}{count > 0 ? ` · ${count}` : ""}</span>
            <button className="anchor-pin" title="钉住为桌面浮窗"
                    onClick={() => { onPin(panel.kind, panel.title); setOpen(false); setPos(null); }}>
              ◱ 钉住
            </button>
          </header>
          <div className="anchor-pop-body"><PanelContent snap={snap} kind={panel.kind} /></div>
        </div>
      )}
    </div>
  );
}

export function AnchorRail({ snap }: { snap: SnapshotMsg | null }) {
  const onPin = (kind: PanelKind, title: string) => {
    void invoke("open_float_panel", { kind, title }).catch(() => {});
  };
  return (
    <aside className="anchor-rail" aria-label="信息锚点">
      {PANELS.map((p) => <Anchor key={p.kind} panel={p} snap={snap} onPin={onPin} />)}
    </aside>
  );
}

/** 浮窗内容：只渲染，不连 runtime（数据由主窗口 push 过来）。 */
export function FloatPanel({ kind, title }: { kind: PanelKind; title: string }) {
  const [snap, setSnap] = useState<SnapshotMsg | null>(null);
  useEffect(() => {
    let off: (() => void) | void;
    void import("@tauri-apps/api/event").then(({ listen }) => {
      void listen<string>("float://data", (e) => {
        try { setSnap(JSON.parse(e.payload) as SnapshotMsg); } catch { /* 忽略非法数据 */ }
      }).then((fn) => { off = fn; });
    });
    return () => { off?.(); };
  }, []);
  const close = () => { void invoke("close_float_panel", { label: `float-${kind}` }).catch(() => {}); };
  return (
    <div className="float-panel">
      <header className="float-head" data-tauri-drag-region>
        <span data-tauri-drag-region>{title}</span>
        <button className="float-close" onClick={close} title="关闭浮窗">×</button>
      </header>
      <div className="float-body"><PanelContent snap={snap} kind={kind} /></div>
    </div>
  );
}
