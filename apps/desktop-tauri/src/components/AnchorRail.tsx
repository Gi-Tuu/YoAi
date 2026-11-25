/** 右侧信息锚点：悬停即出原生浮窗（可浮出桌面），跨窗口 hover 用 Tauri 事件协调。
 *  对齐你的设计：悬停方块 → 原生窗贴着方块出现；移开收回；点击浮窗内容则钉住常驻。 */

import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { SnapshotMsg } from "../types/ipc";

export type PanelKind = "facts" | "goals" | "memory";

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

/** 主窗口侧的锚点方块：悬停即让 Rust 建/定位原生浮窗，并广播 hover 信号。 */
export function AnchorRail({ snap }: { snap: SnapshotMsg | null }) {
  const enter = (kind: PanelKind, title: string, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    void invoke("hover_float_panel", {
      kind, title, x: r.left, y: r.top, width: r.width, height: r.height,
    }).then(() => {
      void invoke("float_hover_signal", { kind, entering: true });
    }).catch(() => {});
  };
  const leave = (kind: PanelKind) => {
    void invoke("float_hover_signal", { kind, entering: false }).catch(() => {});
  };
  return (
    <aside className="anchor-rail" aria-label="信息锚点">
      {PANELS.map((p) => {
        const count = countOf(snap, p.kind);
        return (
          <button
            key={p.kind}
            className="anchor-tile"
            title={`${p.title} · ${count}`}
            onMouseEnter={(e) => enter(p.kind, p.title, e.currentTarget)}
            onMouseLeave={() => leave(p.kind)}
            onFocus={(e) => enter(p.kind, p.title, e.currentTarget)}
            onBlur={() => leave(p.kind)}
          >
            <span className="anchor-glyph">{p.glyph}</span>
            {count > 0 && <span className="anchor-badge">{count}</span>}
          </button>
        );
      })}
    </aside>
  );
}

/** 浮窗内容：跨窗口 hover 协调——锚点或浮窗任一进入则保持，都离开 250ms 后自动收起；
 *  点击内容区则钉住（不再自动收起）。不连 runtime，数据由主窗口 push。 */
export function FloatPanel({ kind, title }: { kind: PanelKind; title: string }) {
  const [snap, setSnap] = useState<SnapshotMsg | null>(null);
  const [pinned, setPinned] = useState(false);
  const pinnedRef = useRef(false);
  const inPanel = useRef(false);
  const inAnchor = useRef(false);
  const timer = useRef<number | null>(null);
  const decide = () => {
    if (timer.current !== null) { clearTimeout(timer.current); timer.current = null; }
    if (pinnedRef.current || inPanel.current || inAnchor.current) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void invoke("close_float_panel", { label: `float-${kind}` }).catch(() => {});
    }, 250);
  };
  const decideRef = useRef(decide);
  decideRef.current = decide;
  const togglePin = () => {
    pinnedRef.current = !pinnedRef.current;
    setPinned(pinnedRef.current);
    decideRef.current();
  };

  useEffect(() => {
    let offData: (() => void) | void;
    let offHover: (() => void) | void;
    void listen<string>("float://data", (e) => {
      try { setSnap(JSON.parse(e.payload) as SnapshotMsg); } catch { /* 忽略非法数据 */ }
    }).then((fn) => { offData = fn; });
    void listen<{ kind: string; entering: boolean }>("float://hover-signal", (e) => {
      if (e.payload.kind !== kind) return;
      inAnchor.current = e.payload.entering;
      decideRef.current();
    }).then((fn) => { offHover = fn; });
    return () => { offData?.(); offHover?.(); };
  }, [kind]);

  const close = () => { void invoke("close_float_panel", { label: `float-${kind}` }).catch(() => {}); };
  return (
    <div className="float-panel"
         onMouseEnter={() => { inPanel.current = true; decideRef.current(); }}
         onMouseLeave={() => { inPanel.current = false; decideRef.current(); }}>
      <header className="float-head" data-tauri-drag-region>
        <span data-tauri-drag-region>{title}{pinned ? " · 已钉住" : ""}</span>
        <button className="float-close" onClick={close} title="关闭浮窗">×</button>
      </header>
      <div className="float-body" onClick={togglePin}
           title="点击内容区可钉住/取消钉住">
        <PanelContent snap={snap} kind={kind} />
      </div>
    </div>
  );
}
