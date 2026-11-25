/** 右栏卡片：个人事实 / 长期目标 / 本轮记忆写入统计。
 *  对齐旧 PySide6 端 SectionCard + MemoryWriteSummary 的信息结构。 */

import type { SnapshotMsg } from "../types/ipc";

const GOAL_MARKS: Record<string, string> = {
  pending: "○", active: "●", done: "✓", cancelled: "×",
};

export function SideCards({ snap }: { snap: SnapshotMsg | null }) {
  const facts = Object.entries(snap?.facts ?? {});
  const goals = snap?.goals ?? [];
  const stats = snap?.write_stats ?? {};
  const events = Number(stats.events ?? 0);
  const sources = ([["model", "模型"], ["fallback", "规则兜底"], ["supplement", "数字补充"]] as const)
    .filter(([k]) => Number(stats[k] ?? 0) > 0)
    .map(([, label]) => label);

  return (
    <aside className="side-cards">
      <section className="side-card">
        <header><span>个人事实</span><span className="count">{facts.length}</span></header>
        <div className="side-card-body">
          {facts.length === 0 && <div className="side-empty">还没有个人事实。</div>}
          {facts.map(([k, v]) => (
            <div key={k} className="side-row" title={`${k} · ${v}`}>
              <span className="side-key">{k}</span>
              <span className="side-val">{v}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="side-card">
        <header><span>长期目标</span><span className="count">{goals.length}</span></header>
        <div className="side-card-body">
          {goals.length === 0 && <div className="side-empty">还没有长期目标。</div>}
          {goals.map((g) => (
            <div key={g.id} className="side-row"
                 title={`状态：${g.status}\nID：${g.id}`}>
              <span className="side-mark">{GOAL_MARKS[g.status] ?? "○"}</span>
              <span className="side-val">{g.title}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="side-card">
        <header><span>本轮记忆</span></header>
        <div className="side-card-body">
          <div className={events ? "mem-line" : "mem-line dim"}>
            {events ? `本轮记忆 +${events}` : "本轮未写入记忆"}
          </div>
          <div className="mem-src">时间记忆 · {sources.length ? sources.join("、") : "无新增"}</div>
        </div>
      </section>
    </aside>
  );
}
