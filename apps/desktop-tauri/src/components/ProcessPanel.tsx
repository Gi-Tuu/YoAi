/** Agent 过程面板：默认折叠、虚拟化长列表、增量更新。
 *  性能要点（任务阶段 E）：
 *  - TanStack Virtual 只渲染可视范围 + overscan，1万条不建 1万个 DOM
 *  - 事件数组由 useTaskStream 增量追加，本组件不重解析历史
 *  - 实时区（当前活动）与历史虚拟列表分开，展开历史不影响实时上屏
 *  - 折叠/展开只切换本组件局部 state，不触发全量重建
 */

import { useMemo, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ProcEvent } from "../hooks/useTaskStream";

const EVENT_LABELS: Record<string, string> = {
  strategy_selected: "路由", plan_created: "制定计划", tool_call: "调用工具",
  tool_result: "工具完成", permission_asked: "请求授权", permission_denied: "拒绝授权",
  clarify_requested: "需要澄清", capability_missing: "能力缺口",
  tool_discovered: "发现工具", tool_composed: "组合工具",
  code_tool_created: "创建代码工具", code_tool_retired: "停用代码工具",
  context_compacted: "压缩上下文", memories_recalled: "召回记忆",
  plan_revised: "修订计划", tier_changed: "切换档位",
  budget_exceeded: "预算超限", error: "出错", done: "完成",
};

function describe(e: ProcEvent): { label: string; text: string; kind: string } {
  const label = EVENT_LABELS[e.name] ?? e.name;
  const d = e.data;
  if (e.name === "strategy_selected") return { label, text: String(d.strategy ?? ""), kind: "" };
  if (e.name === "tool_call") return { label, text: `${d.tool ?? ""} ${shortJson(d.arguments)}`, kind: "step" };
  if (e.name === "tool_result") return { label, text: `${d.tool ?? ""} ${short(String(d.result ?? ""))}`, kind: "result" };
  if (e.name === "error" || e.name === "permission_denied" || e.name === "budget_exceeded") {
    return { label, text: String(d.error ?? d.reason ?? d.message ?? ""), kind: "bad" };
  }
  return { label, text: shortJson(d), kind: "" };
}

function short(s: string, n = 200): string { return s.length > n ? s.slice(0, n) + "…" : s; }
function shortJson(v: unknown): string { return short(typeof v === "string" ? v : JSON.stringify(v ?? {})); }

interface Props {
  events: ProcEvent[];
  thinking: string;
}

export function ProcessPanel({ events, thinking }: Props) {
  const [expanded, setExpanded] = useState(false);   // 默认折叠
  const [thinkOpen, setThinkOpen] = useState(false); // 思考默认折叠
  const parentRef = useMemo(() => ({ current: null as HTMLDivElement | null }), []);

  // 实时区：只显示最后 3 条活动（不随历史增长）
  const live = events.slice(-3);
  const rows = useMemo(() => events.map(describe), [events]);

  const virtualizer = useVirtualizer({
    count: expanded ? rows.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 34,
    overscan: 12,
  });

  const tools = rows.filter((r) => r.kind === "step").length;

  return (
    <section className="process-panel" aria-label="Agent 过程">
      <button className="process-toggle" onClick={() => setExpanded((v) => !v)}>
        <span>{expanded ? "▾" : "▸"} 执行过程 · {events.length} 条记录{tools ? ` · ${tools} 步` : ""}</span>
        {thinking.trim() && (
          <span className="think-link" role="button" tabIndex={0}
                onClick={(e) => { e.stopPropagation(); setThinkOpen((v) => !v); }}
                onKeyDown={(e) => { if (e.key === "Enter") setThinkOpen((v) => !v); }}>
            {thinkOpen ? "▾ 收起思考过程" : `▸ 查看思考过程（${thinking.length} 字）`}
          </span>
        )}
      </button>

      {thinkOpen && thinking.trim() && (
        <div className="think-block">[思考] {thinking}</div>
      )}

      {/* 实时活动：始终显示最新 3 条，展开历史不影响它 */}
      {!expanded && live.length > 0 && (
        <div className="process-live">
          {live.map((e) => { const r = describe(e); return (
            <div key={e.seq} className={`proc-row ${r.kind}`}>
              <span className="proc-label">[{r.label}]</span> {r.text}
            </div>
          ); })}
        </div>
      )}

      {/* 历史：虚拟化，只渲染可视范围 */}
      {expanded && (
        <div ref={parentRef} className="process-scroll">
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((item) => {
              const r = rows[item.index];
              if (!r) return null;
              return (
                <div key={item.key} className={`proc-row ${r.kind}`}
                     style={{ position: "absolute", top: 0, left: 0, width: "100%",
                              height: item.size, transform: `translateY(${item.start}px)` }}>
                  <span className="proc-label">[{r.label}]</span> {r.text}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
