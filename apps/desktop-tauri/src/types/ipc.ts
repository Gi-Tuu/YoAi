/** Desktop IPC 协议 v1 的 TypeScript 类型。与 docs/IPC-PROTOCOL.md / runtime/protocol.py 一一对应。
 *  改协议必须同步改这三处。
 *  v1 扩展（会话管理/通讯/星图）：追加消息类型，旧消息不变。
 */

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
  created_at?: string;
  last_active?: string;
}

export interface HistoryEntry {
  role: string;
  text: string;
}

export interface GoalInfo {
  id: string;
  title: string;
  status: string;
}

export interface ThinkingRecord {
  run_id: string;
  session_id: string;
  at: string;
  text: string;
  input?: string;
}

/** 会话全景（旧端主窗口侧栏数据源的等价物）。 */
export interface SnapshotMsg extends BaseMsg {
  type: "snapshot";
  sessions: SessionInfo[];
  current_id: string;
  history: HistoryEntry[];
  model: string;
  facts: Record<string, string>;
  goals: GoalInfo[];
  write_stats: Record<string, number>;
  tools: string[];
  thinking_log: ThinkingRecord[];   // 历史 thinking（YoAi 侧持久化）
}

export interface ChatEntry {
  sender: string;
  name: string;
  content: string;
  own: boolean;
}

export interface ConversationInfo {
  id: string;
  name: string;
  kind: "peer" | "group";
  members: number;
}

export interface ExternalAgentInfo {
  name: string;
  level: string;
  available: boolean;
}

export interface ChatStateMsg extends BaseMsg {
  type: "chat.state";
  conversations: ConversationInfo[];
  external: ExternalAgentInfo[];
  history_target?: string;
  history?: ChatEntry[];
}

export interface ChatMsgMsg extends BaseMsg {
  type: "chat.msg";
  target: string;
  sender: string;
  name: string;
  content: string;
  own: boolean;
  at?: string;
}

export interface ArchiveNode {
  id: string;
  name: string;
  lifecycle: string;
  version: number;
  parent_id: string;
  depth: number;
  capability_tags: string[];
  tools: string[];
  strategy_bias: string;
  model_tier: string;
  diff: string;
  evidence_count: number;
  created_at: string;
  prompt_suffix: string;
}

export interface ArchiveStateMsg extends BaseMsg {
  type: "archive.state";
  nodes: ArchiveNode[];
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
  | ReadyMsg | StatusMsg | EventMsg | FinalMsg | ApprovalRequestMsg | ErrorMsg
  | SnapshotMsg | ChatStateMsg | ChatMsgMsg | ArchiveStateMsg;

// ---- 命令（前端 → Python）----
export type Command =
  | { v: 1; type: "hello"; client: string; protocol: number }
  | { v: 1; type: "task.start"; task_id: string; run_id: string; input: string }
  | { v: 1; type: "task.cancel"; task_id: string; run_id: string }
  | { v: 1; type: "session.state" }
  | { v: 1; type: "session.create"; name: string }
  | { v: 1; type: "session.switch"; session_id: string }
  | { v: 1; type: "session.rename"; session_id: string; name: string }
  | { v: 1; type: "session.delete"; session_id: string }
  | { v: 1; type: "chat.state" }
  | { v: 1; type: "chat.history"; target: string }
  | { v: 1; type: "chat.send"; target: string; text: string }
  | { v: 1; type: "chat.new_group"; name: string }
  | { v: 1; type: "chat.add_member"; target: string; peer_id: string }
  | { v: 1; type: "chat.add_external"; target: string; name: string }
  | { v: 1; type: "archive.get" }
  | { v: 1; type: "config.get" }
  | { v: 1; type: "config.set"; patch: Record<string, unknown> }
  | { v: 1; type: "approval.reply"; task_id: string; run_id: string; allow: boolean }
  | { v: 1; type: "clarify.reply"; task_id: string; run_id: string; answer: string }
  | { v: 1; type: "shutdown" };
