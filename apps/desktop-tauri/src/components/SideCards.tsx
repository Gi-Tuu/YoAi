import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { SnapshotMsg } from "../types/ipc";

const GOAL_MARKS: Record<string, string> = {
  pending: "○", active: "●", done: "✓", cancelled: "×",
};

const HOVER_DELAY = 1.5;
const TILE_SIZE = 58;
const TILE_GAP = 12;
const PANEL_HEIGHT = 176;
const EDGE = 8;

type OpenCard = { id: string; anchor: number; x: number; pinned: boolean };

interface Card {
  id: string;
  title: string;
  panelTitle?: string;
  count?: number;
  icon?: string;
  width?: number;
  height?: number;
  body: ReactNode;
}

export function SideCards({ snap, extraCards = [], onFilesOpen, toolNotice }: {
  snap: SnapshotMsg | null;
  extraCards?: Card[];
  onFilesOpen?: (opened: boolean) => void;
  toolNotice?: string;
}) {
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

  const cards: Card[] = [
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
    ...extraCards,
  ];
  const filesOpen = open.some((panel) => panel.id === "files");
  useEffect(() => { onFilesOpen?.(filesOpen); }, [filesOpen, onFilesOpen]);

  const tileSize = Math.max(36, Math.min(TILE_SIZE,
    (space.height - 2 * EDGE - (cards.length - 1) * TILE_GAP) / cards.length));
  const clampY = (y: number, half: number) =>
    Math.max(half + EDGE, Math.min(y, space.height - half - EDGE));
  const panels = open.map((panel) => {
    const card = cards.find(({ id }) => id === panel.id);
    const width = card?.width ?? 300;
    const height = Math.max(0, Math.min(card?.height ?? PANEL_HEIGHT, space.height - EDGE * 2));
    const x = Math.min(panel.x * space.width, space.width - width / 2 - EDGE);
    const y = clampY(panel.anchor * space.height, height / 2);
    return { x, y, width, height };
  });
  const occupied = [...panels];

  return (
    <aside className="side-cards" aria-label="会话资料与工具" ref={rail}
           onKeyDown={(event) => {
             if (event.key === "Escape") setOpen((previous) => previous.filter((panel) => panel.pinned));
           }}>
      {cards.map(({ id, title, panelTitle = title, count, body, icon }, index) => {
        const layer = open.findIndex((panel) => panel.id === id);
        const panel = open[layer];
        const targetY = space.height / 2 + (index - (cards.length - 1) / 2) * (tileSize + TILE_GAP);
        const idForPanel = panelId + id;
        const geometry = panels[layer];
        if (panel && geometry) {
          const { x, y, width, height } = geometry;
          return (
            <section key={id} id={idForPanel} className="side-card" aria-label={panelTitle}
                     data-pinned={panel.pinned}
                     style={{ width, height, top: y, left: x,
                       zIndex: layer + 1,
                       transformOrigin: `${panel.x * space.width - x + width / 2}px ${panel.anchor * space.height - y + height / 2}px` }}
                     onPointerEnter={() => cancelTimer(id)}
                     onPointerLeave={() => { if (!panel.pinned) afterHover(id, () => dismiss(id)); }}
                     onClick={() => expand(id, panel.anchor, panel.x, true)}
                     onFocus={() => cancelTimer(id)}
                     onBlur={(event) => {
                       if (!panel.pinned && !event.currentTarget.contains(event.relatedTarget)) dismiss(id);
                     }}>
              <div className="side-card-surface">
                <header>{panelTitle}
                  {panel.pinned && (
                    <button type="button" className="side-card-close" aria-label={`收起${title}`}
                            onClick={(event) => { event.stopPropagation(); dismiss(id, true); }}>×</button>
                  )}
                </header>
                {icon ? <>
                  {toolNotice && <div className="tool-notice">{toolNotice}</div>}
                  {body}
                </> : (
                  <div className="side-card-body" tabIndex={0}
                       onKeyDown={(event) => { if (event.key === "Enter") expand(id, panel.anchor, panel.x, true); }}>{body}</div>
                )}
              </div>
            </section>
          );
        }
        const half = tileSize / 2;
        const center = space.width / 2;
        const valid = (x: number, y: number) =>
          occupied.every((item) => Math.abs(y - item.y) >= item.height / 2 + half + EDGE ||
            Math.abs(x - item.x) >= item.width / 2 + half + EDGE);
        const candidates = [clampY(targetY, half), ...occupied.flatMap((item) =>
          [item.y - item.height / 2 - half - EDGE, item.y + item.height / 2 + half + EDGE])]
          .filter((y) => y === clampY(y, half))
          .sort((a, b) => Math.abs(a - targetY) - Math.abs(b - targetY));
        const aligned = candidates.find((y) => valid(center, y));
        const fallback = Math.min(center, ...panels.map((item) => item.x - item.width / 2 - half - EDGE));
        const left = aligned === undefined ? fallback : center;
        const y = aligned ?? candidates.find((candidate) => valid(left, candidate)) ?? clampY(targetY, half);
        occupied.push({ x: left, y, width: tileSize, height: tileSize });
        const anchor = y / space.height;
        return (
          <button key={id} className="side-tile" type="button" style={{ top: y, left, width: tileSize }}
                  aria-expanded={false} aria-controls={idForPanel}
                  onPointerEnter={(event) => {
                    if (event.pointerType !== "touch") afterHover(id, () => expand(id, anchor, left / space.width));
                  }}
                  onPointerLeave={() => cancelTimer(id)}
                  onClick={() => expand(id, anchor, left / space.width, true)}>
            {icon && <span className="dock-icon" aria-hidden="true">{icon}</span>}
            <span>{title}</span>
            {count !== undefined && <span className="count">{count}</span>}
          </button>
        );
      })}
    </aside>
  );
}
