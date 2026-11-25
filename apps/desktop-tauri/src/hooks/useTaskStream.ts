/** 任务流状态：增量追加事件，不为每条事件重建全部历史。
 *  - 事件按 run_id 聚合到 Map，React 状态只追加不重解析
 *  - thinking/delta 合并成段（碎片 token 不逐条成行）
 *  - 流式期间用节流批量 setState，首块立即上屏
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { EventMsg, RuntimeMsg, StatusMsg } from "../types/ipc";

export interface ProcEvent {
  seq: number;
  name: string;
  data: Record<string, unknown>;
  at: number;
}

export interface RunState {
  taskId: string;
  runId: string;
  input: string;
  state: string;
  detail: string;
  events: ProcEvent[];
  streamText: Map<number, string>;   // round -> 累积流式文本
  thinking: string;                  // 累积思考（默认折叠）
  finalText: string;
  approval: { tool: string; question: string; detail: string } | null;
  startedAt: number;
  endedAt?: number;
}

const emptyRun = (taskId: string, runId: string, input: string): RunState => ({
  taskId, runId, input, state: "queued", detail: "", events: [],
  streamText: new Map(), thinking: "", finalText: "", approval: null,
  startedAt: Date.now(),
});

export function useTaskStream(messages: RuntimeMsg[]) {
  const [runs, setRuns] = useState<Map<string, RunState>>(() => new Map());
  const [activeRunId, setActiveRunId] = useState<string>("");
  const pending = useRef<RuntimeMsg[]>([]);
  const timer = useRef<number | null>(null);
  // 增量消费游标：messages 是只增数组（发送时重置为 []），只处理新到的部分，
  // 否则每次全量重推会让同一事件被重复追加进 runs。
  const processed = useRef(0);

  const flush = useCallback(() => {
    timer.current = null;
    const batch = pending.current;
    pending.current = [];
    if (!batch.length) return;
    setRuns((prev) => {
      // 复制 Map 外壳 + 受影响的 run 对象（结构共享，不重建全部历史）
      const next = new Map(prev);
      for (const msg of batch) {
        if (msg.type === "status") {
          const s = msg as StatusMsg;
          const key = s.run_id;
          const run = next.get(key) ?? emptyRun(s.task_id, s.run_id, "");
          next.set(key, { ...run, state: s.state, detail: s.detail,
                          endedAt: s.state === "done" || s.state === "failed" || s.state === "cancelled" ? Date.now() : undefined });
          setActiveRunId(key);
        } else if (msg.type === "event") {
          const e = msg as EventMsg;
          const run = next.get(e.run_id) ?? emptyRun(e.task_id, e.run_id, "");
          if (e.event === "delta") {
            const round = Number(e.data.round ?? 0);
            const text = String(e.data.text ?? "");
            const st = new Map(run.streamText);
            st.set(round, (st.get(round) ?? "") + text);
            next.set(e.run_id, { ...run, streamText: st });
          } else if (e.event === "thinking") {
            next.set(e.run_id, { ...run, thinking: run.thinking + String(e.data.text ?? "") });
          } else {
            // 过程事件：追加，不重解析既有
            next.set(e.run_id, { ...run, events: [...run.events, {
              seq: e.seq, name: e.event, data: e.data, at: Date.now(),
            }] });
          }
        } else if (msg.type === "final") {
          const run = next.get(msg.run_id) ?? emptyRun(msg.task_id, msg.run_id, "");
          next.set(msg.run_id, { ...run, finalText: msg.text });
        } else if (msg.type === "approval.request") {
          const run = next.get(msg.run_id) ?? emptyRun(msg.task_id, msg.run_id, "");
          next.set(msg.run_id, { ...run, approval: {
            tool: msg.tool, question: msg.question, detail: msg.detail,
          } });
        }
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (messages.length < processed.current) {
      processed.current = 0;   // App 在发送新任务时清空数组 → 重置游标
    }
    if (messages.length > processed.current) {
      pending.current.push(...messages.slice(processed.current));
      processed.current = messages.length;
    }
    if (timer.current === null) {
      // 立即 flush：ipc 层已用 requestAnimationFrame 批量（每帧一次），
      // 这里再加 16ms 节流会让流式 token 攒成一段蹦出来——去掉。
      timer.current = window.setTimeout(flush, 0);
    }
    return () => { /* timer 跨消息存活，由 flush 自清 */ };
  }, [messages, flush]);

  useEffect(() => () => { if (timer.current !== null) clearTimeout(timer.current); }, []);

  const beginRun = useCallback((taskId: string, runId: string, input: string) => {
    setRuns((prev) => {
      const next = new Map(prev);
      next.set(runId, emptyRun(taskId, runId, input));
      return next;
    });
    setActiveRunId(runId);
  }, []);

  const clearApproval = useCallback((runId: string) => {
    setRuns((prev) => {
      const run = prev.get(runId);
      if (!run) return prev;
      const next = new Map(prev);
      next.set(runId, { ...run, approval: null });
      return next;
    });
  }, []);

  /** 切换会话/清空视图：丢弃全部 run 状态（历史由 snapshot.history 承担）。 */
  const resetRuns = useCallback(() => {
    setRuns(new Map());
    setActiveRunId("");
  }, []);

  return { runs, activeRunId, beginRun, clearApproval, resetRuns };
}

/** 只在用户停留底部时自动跟随新内容。 */
export function useStickToBottom<T extends HTMLElement>(dep: unknown) {
  const ref = useRef<T | null>(null);
  const stick = useRef(true);
  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }, []);
  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [dep]);
  return { ref, onScroll };
}
