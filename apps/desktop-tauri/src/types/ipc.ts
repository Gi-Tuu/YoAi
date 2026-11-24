/** Desktop IPC 协议 v1 的 TypeScript 类型。与 docs/IPC-PROTOCOL.md / runtime/protocol.py 一一对应。
 *  改协议必须同步改这三处。 */

export const PROTOCOL_VERSION = 1;

export type TaskState = "queued" | "running" | "done" | "failed" | "cancelled";

export interface BaseMsg {
  v: number;
  type: string;
  task_id?: string;
  run_id?: string;
  seq?: number;
}

export interface ReadyMsg extends BaseMsg {
  type: "ready";
  protocol: number;
  python: string;
  tools: string[];
  sessions: SessionInfo[];
  config: Record<string, unknown>;
}

export interface SessionInfo {
  id: string;
  name: string;
  updated_at?: string;
}

export interface StatusMsg extends BaseMsg {
  type: "status";
  task_id: string;
  run_id: string;
  seq: number;
  state: TaskState;
  detail: string;
}

/** Core EventType 全表 + YoAi 自定义 thinking/delta。 */
export type EventName =
  | "strategy_selected" | "plan_created" | "model_message" | "tool_call"
  | "tool_result" | "permission_asked" | "permission_denied"
  | "clarify_requested" | "capability_missing" | "tool_discovered"
  | "tool_composed" | "code_tool_created" | "code_tool_retired"
  | "context_compacted" | "memories_recalled" | "host_state"
  | "plan_revised" | "tier_changed" | "budget_exceeded" | "error" | "done"
  | "thinking" | "delta";

export interface EventMsg extends BaseMsg {
  type: "event";
  task_id: string;
  run_id: string;
  seq: number;
  event: EventName;
  data: Record<string, unknown>;
}

export interface FinalMsg extends BaseMsg {
  type: "final";
  task_id: string;
  run_id: string;
  seq: number;
  text: string;
}

export interface ApprovalRequestMsg extends BaseMsg {
  type: "approval.request";
  task_id: string;
  run_id: string;
  seq: number;
  tool: string;
  question: string;
  detail: string;
}

export interface ErrorMsg extends BaseMsg {
  type: "error";
  stage: "startup" | "runtime" | "protocol";
  message: string;
}

export type RuntimeMsg =
  | ReadyMsg | StatusMsg | EventMsg | FinalMsg | ApprovalRequestMsg | ErrorMsg;

// ---- 命令（前端 → Python）----
export type Command =
  | { v: 1; type: "hello"; client: string; protocol: number }
  | { v: 1; type: "task.start"; task_id: string; run_id: string; input: string }
  | { v: 1; type: "task.cancel"; task_id: string; run_id: string }
  | { v: 1; type: "session.list" }
  | { v: 1; type: "session.switch"; session_id: string }
  | { v: 1; type: "config.get" }
  | { v: 1; type: "config.set"; patch: Record<string, unknown> }
  | { v: 1; type: "approval.reply"; task_id: string; run_id: string; allow: boolean }
  | { v: 1; type: "clarify.reply"; task_id: string; run_id: string; answer: string }
  | { v: 1; type: "shutdown" };
