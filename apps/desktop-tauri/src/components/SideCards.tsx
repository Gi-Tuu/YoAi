import { useEffect, useId, useRef, useState } from "react";
import type { SnapshotMsg } from "../types/ipc";

const GOAL_MARKS: Record<string, string> = {
  pending: "○", active: "●", done: "✓", cancelled: "×",
};

const HOVER_DELAY = 1.5;
const TILE_SIZE = 58;
const TILE_STEP = 70;
const PANEL_HEIGHT = 176;
const EDGE = 8;

type OpenCard = { id: string; anchor: number; x: number; pinned: boolean };

export function SideCards({ snap }: { snap: SnapshotMsg | null }) {
  const facts = Object.entries(snap?.facts ?? {});
  const goals = snap?.goals ?? [];
  const stats = snap?.write_stats ?? {};
  const events = Number(stats.events ?? 0);
  const sources = ([["model", "模型"], ["fallback", "规则兜底"], ["supplement", "数字补充"]] as const)
    .filter(([k]) => Number(stats[k] ?? 0) > 0)
    .map(([, label]) => label);

  const [open, setOpen] = useState<OpenCard[]>([]);
  const [space, setSpace] = useState({ width: 74, height: 420 });
  const rail = useRef<HTMLElement>(null);
  const panelId = useId();
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  useEffect(() => {
    const pending = timers.current;
    const element = rail.current;
    const observer = element && typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(([entry]) => { if (entry) setSpace(entry.contentRect); })
      : null;
    if (observer && element) observer.observe(element);
    return () => {
      observer?.disconnect();
      pending.forEach(clearTimeout);
      pending.clear();
    };
  }, []);

  function cancelTimer(id: string) {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
  }

  function afterHover(id: string, action: () => void) {
    cancelTimer(id);
    timers.current.set(id, setTimeout(() => {
      timers.current.delete(id);
      action();
    }, HOVER_DELAY));
  }

  function expand(id: string, anchor: number, x: number, pinned = false) {
    cancelTimer(id);
    setOpen((previous) => {
      const existing = previous.find((panel) => panel.id === id);
      if (!pinned && existing) return previous;
      return [...previous.filter((panel) => panel.id !== id),
        { id, anchor: existing?.anchor ?? anchor, x: existing?.x ?? x, pinned }];
    });
  }

  function dismiss(id: string, force = false) {
    cancelTimer(id);
    setOpen((previous) => previous.filter((panel) => panel.id !== id || (panel.pinned && !force)));
  }

  const cards = [
    {
      id: "facts", title: "个人事实", count: facts.length,
      body: facts.length ? facts.map(([k, v]) => (
        <div key={k} className="side-row">
          <span className="side-key">{k}</span>
          <span className="side-val">{v}</span>
        </div>
      )) : <div className="side-empty">还没有个人事实。</div>,
    },
    {
      id: "goals", title: "长期目标", count: goals.length,
      body: goals.length ? goals.map((g) => (
        <div key={g.id} className="side-row" title={`状态：${g.status} · ID：${g.id}`}>
          <span className="side-mark">{GOAL_MARKS[g.status] ?? "○"}</span>
          <span className="side-val">{g.title}</span>
        </div>
      )) : <div className="side-empty">还没有长期目标。</div>,
    },
    {
      id: "memory", title: "本轮记忆", count: events,
      body: <>
        <div className={events ? "mem-line" : "mem-line dim"}>
          {events ? `本轮记忆 +${events}` : "本轮未写入记忆"}
        </div>
        <div className="mem-src">时间记忆 · {sources.length ? sources.join("、") : "无新增"}</div>
      </>,
    },
  ];
  const panelWidth = 300;
  const panelHeight = Math.max(0, Math.min(PANEL_HEIGHT, space.height - EDGE * 2));
  const clampY = (y: number, half: number) =>
    Math.max(half + EDGE, Math.min(y, space.height - half - EDGE));
  const bounds = open.map((panel) => clampY(panel.anchor * space.height, panelHeight / 2));
  const occupied = bounds.map((y) => ({ y, half: panelHeight / 2 }));
  const panelX = Math.min(space.width / 2, space.width - panelWidth / 2 - EDGE);

  return (
    <aside className="side-cards" aria-label="会话资料" ref={rail}
           onKeyDown={(event) => {
             if (event.key === "Escape") setOpen((previous) => previous.filter((panel) => panel.pinned));
           }}>
      {cards.map(({ id, title, count, body }, index) => {
        const layer = open.findIndex((panel) => panel.id === id);
        const panel = open[layer];
        const targetY = space.height / 2 + (index - 1) * TILE_STEP;
        const idForPanel = panelId + id;
        if (panel) {
          const y = clampY(panel.anchor * space.height, panelHeight / 2);
          const centerX = Math.min(panel.x * space.width, panelX);
          return (
            <section key={id} id={idForPanel} className="side-card" aria-label={title}
                     data-pinned={panel.pinned}
                     style={{ width: panelWidth, height: panelHeight, top: y, left: centerX,
                       zIndex: layer + 1,
                       transformOrigin: `${panel.x * space.width - centerX + panelWidth / 2}px ${panel.anchor * space.height - y + panelHeight / 2}px` }}
                     onPointerEnter={() => cancelTimer(id)}
                     onPointerLeave={() => { if (!panel.pinned) afterHover(id, () => dismiss(id)); }}
                     onClick={() => expand(id, panel.anchor, panel.x, true)}
                     onFocus={() => cancelTimer(id)}
                     onBlur={(event) => {
                       if (!panel.pinned && !event.currentTarget.contains(event.relatedTarget)) dismiss(id);
                     }}>
              <div className="side-card-surface">
                <header>{title}
                  {panel.pinned && (
                    <button type="button" className="side-card-close" aria-label={`收起${title}`}
                            onClick={(event) => { event.stopPropagation(); dismiss(id, true); }}>×</button>
                  )}
                </header>
                <div className="side-card-body" tabIndex={0}
                     onKeyDown={(event) => { if (event.key === "Enter") expand(id, panel.anchor, panel.x, true); }}>{body}</div>
              </div>
            </section>
          );
        }
        let y = clampY(targetY, TILE_SIZE / 2);
        const candidates = [y, ...occupied.flatMap(({ y: center, half }) =>
          [center - half - TILE_SIZE / 2 - EDGE, center + half + TILE_SIZE / 2 + EDGE])]
          .sort((a, b) => Math.abs(a - targetY) - Math.abs(b - targetY));
        const available = candidates.find((candidate) =>
          candidate === clampY(candidate, TILE_SIZE / 2) &&
          occupied.every(({ y: center, half }) => Math.abs(candidate - center) >= half + TILE_SIZE / 2 + EDGE));
        if (available !== undefined) y = available;
        occupied.push({ y, half: TILE_SIZE / 2 });
        const anchor = y / space.height;
        const left = available === undefined ? panelX - panelWidth / 2 - TILE_SIZE / 2 - EDGE : space.width / 2;
        return (
          <button key={id} className="side-tile" type="button" style={{ top: y, left }}
                  aria-expanded={false} aria-controls={idForPanel}
                  onPointerEnter={(event) => {
                    if (event.pointerType !== "touch") afterHover(id, () => expand(id, anchor, left / space.width));
                  }}
                  onPointerLeave={() => cancelTimer(id)}
                  onClick={() => expand(id, anchor, left / space.width, true)}>
            <span>{title}</span>
            <span className="count">{count}</span>
          </button>
        );
      })}
    </aside>
  );
}
