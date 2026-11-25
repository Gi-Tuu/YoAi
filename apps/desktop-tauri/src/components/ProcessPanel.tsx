/** 可独立展开执行记录和思考内容的过程面板。 */

import { useMemo, useRef, useState } from "react";
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
  if (e.name === "tool_call") return { label, text: `${d.tool ?? ""} ${formatValue(d.arguments)}`, kind: "step" };
  if (e.name === "tool_result") return { label, text: `${d.tool ?? ""} ${formatValue(d.result ?? "")}`, kind: "result" };
  if (e.name === "error" || e.name === "permission_denied" || e.name === "budget_exceeded") {
    return { label, text: String(d.error ?? d.reason ?? d.message ?? ""), kind: "bad" };
  }
  return { label, text: formatValue(d), kind: "" };
}

function formatValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value ?? {});
}

interface Props {
  events: ProcEvent[];
  thinking: string;
}

const ROW_HEIGHT = 32;
const VISIBLE_ROWS = 8;

function ProcessRow({ event }: { event: ProcEvent }) {
  const row = describe(event);
  return <div className={`proc-row ${row.kind}`} title={row.text}>
    <span className="proc-label">[{row.label}]</span> {row.text}
  </div>;
}

function LongProcessList({ events }: { events: ProcEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: events.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });
  return (
    <div ref={scrollRef} className="process-scroll" style={{ height: ROW_HEIGHT * VISIBLE_ROWS }}>
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((item) => {
          const event = events[item.index];
          return event && (
            <div key={item.key} data-index={item.index} ref={virtualizer.measureElement}
                 style={{ position: "absolute", inset: "0 0 auto",
                                        transform: `translateY(${item.start}px)` }}>
              <ProcessRow event={event} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ProcessPanel({ events, thinking }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [thinkOpen, setThinkOpen] = useState(false);
  const tools = useMemo(() => events.filter((event) => event.name === "tool_call").length, [events]);

  return (
    <section className="process-panel" aria-label="Agent 过程">
      <div className="process-head">
        <button type="button" className="process-toggle" aria-expanded={expanded}
                onClick={() => setExpanded((v) => !v)}>
          {expanded ? "▾" : "▸"} 执行过程 · {events.length} 条记录{tools ? ` · ${tools} 步` : ""}
        </button>
        {thinking.trim() && (
          <button type="button" className="process-toggle think-link" aria-expanded={thinkOpen}
                  onClick={() => setThinkOpen((v) => !v)}>
            {thinkOpen ? "▾ 收起思考过程" : `▸ 查看思考过程（${thinking.length} 字）`}
          </button>
        )}
      </div>

      {thinkOpen && thinking.trim() && <div className="think-block">[思考] {thinking}</div>}

      {expanded && (events.length > VISIBLE_ROWS ? <LongProcessList events={events} /> : (
        <div className="process-list">
          {events.length ? events.map((event) => <ProcessRow key={event.seq} event={event} />)
            : <div className="proc-row">暂无执行记录</div>}
        </div>
      ))}
    </section>
  );
}
