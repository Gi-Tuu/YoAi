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
  mode?: "chat" | "project";   // 聊天模式(沙箱) | 项目模式(可写项目文件夹)
  project_id?: string;
}

export interface ProjectInfo {
  id: string;
  name: string;
  path: string;
  created_at: string;
}

export interface DiffOp { kind: "context" | "add" | "remove"; text: string; old_line?: number; new_line?: number; }
export interface FileChangeRecord {
  id: string; at: string; path: string; action: "create" | "patch";
  added: number; removed: number; diff: DiffOp[];
  session_id: string; project_id: string; run_id: string;
  after?: string;  // 产物(create)带全文供下载；改动(patch)省略
}

export interface FileChangedMsg extends BaseMsg {
  type: "file.changed";
  task_id: string; run_id: string; seq: number;
  change: FileChangeRecord;
}

export interface AttachmentInfo {
  id: string;
  name: string;
  size: number;
  path: string;
  content: string;
  truncated: boolean;
}

export interface HistoryEntry {
  role: string;
  text: string;
  at?: string;
  idx?: number;                 // 原始 Core 历史序号（撤回/编辑定位用）
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
  model_id?: string;
  model_options?: { id: string; label: string }[];
  context_usage?: { used: number; limit: number };
  facts: Record<string, string>;
  goals: GoalInfo[];
  write_stats: Record<string, number>;
  tools: string[];
  thinking_log: ThinkingRecord[];   // 历史 thinking（YoAi 侧持久化）
  projects?: ProjectInfo[];          // 项目列表
  artifacts?: FileChangeRecord[];     // 新建文件（产物）
  changes?: FileChangeRecord[];       // 修改文件（改动）
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

export interface ArchiveEvidence {
  id: string;
  kind: string;
  task_fingerprint: string;
  outcome: string;
  detail: string;
  created_at: string;
}

export interface EvolutionReportSummary {
  id: string;
  evidence_id: string;
  triggered: boolean;
  cause: string;
  new_node_id: string | null;
  reason: string;
  created_at: string;
  promotion?: { promoted: boolean; reason: string; report?: {
    verdict: string; note: string; total_samples: number;
    boundaries: Array<{ capability_tag: string; node_rate: number; parent_rate: number;
      node_ci: number[]; parent_ci: number[]; sample_enough: boolean }>;
  } | null } | null;
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
  evidence?: ArchiveEvidence[];
  reports?: EvolutionReportSummary[];
  created_at: string;
  prompt_suffix: string;
}

export interface ArchiveStateMsg extends BaseMsg {
  type: "archive.state";
  nodes: ArchiveNode[];
}

export type PermissionLevel = "full" | "smart" | "manual";

export interface PermissionStateMsg extends BaseMsg {
  type: "permission.state";
  level: PermissionLevel;
  description: string;
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
  stage: "startup" | "runtime" | "protocol" | "file" | "browser" | "message" | "share";
  message: string;
}

export interface AttachmentReadyMsg extends BaseMsg {
  type: "attachment.ready";
  attachment: AttachmentInfo;
}

export interface MessageUpdatedMsg extends BaseMsg {
  type: "message.updated";
  kind: "retract" | "edit" | "regenerate";
  index: number;
  detail: string;
}

export interface ShareExportedMsg extends BaseMsg {
  type: "share.exported";
  path: string;
  count: number;
}

/** 右侧工具面板：系统浏览器兜底已触发。 */
export interface BrowserOpenedMsg extends BaseMsg {
  type: "browser.opened";
  url: string;
}

export interface FileEntry {
  name: string;
  path: string;       // 相对根目录
  is_dir: boolean;
}

export interface FileTreeMsg extends BaseMsg {
  type: "file.tree";
  root: string;
  label: string;
  path: string;
  entries: FileEntry[];
}

export interface FileContentMsg extends BaseMsg {
  type: "file.content";
  root: string;
  path: string;
  content: string;
  size: number;
  truncated: boolean;
}

export type RuntimeMsg =
  | ReadyMsg | StatusMsg | EventMsg | FinalMsg | ApprovalRequestMsg | ErrorMsg
  | SnapshotMsg | ChatStateMsg | ChatMsgMsg | ArchiveStateMsg | PermissionStateMsg
  | FileChangedMsg | BrowserOpenedMsg | FileTreeMsg | FileContentMsg
  | AttachmentReadyMsg | MessageUpdatedMsg | ShareExportedMsg;

// ---- 命令（前端 → Python）----
export type Command =
  | { v: 1; type: "hello"; client: string; protocol: number }
  | { v: 1; type: "task.start"; task_id: string; run_id: string; input: string }
  | { v: 1; type: "task.cancel"; task_id: string; run_id: string }
  | { v: 1; type: "session.state" }
  | { v: 1; type: "session.create"; name: string }
  | { v: 1; type: "model.select"; model_id: string }
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
  | { v: 1; type: "permission.get" }
  | { v: 1; type: "permission.set"; level: PermissionLevel }
  | { v: 1; type: "project.create"; name: string; path: string; session_name?: string }
  | { v: 1; type: "project.list" }
  | { v: 1; type: "project.delete"; project_id: string }
  | { v: 1; type: "session.new_in_project"; project_id: string; name?: string }
  | { v: 1; type: "browser.open"; url: string }
  | { v: 1; type: "fs.list"; path: string }
  | { v: 1; type: "fs.read"; path: string }
  | { v: 1; type: "attachment.prepare"; path: string }
  | { v: 1; type: "attachment.remove"; id: string }
  | { v: 1; type: "message.retract"; index: number }
  | { v: 1; type: "message.edit"; index: number; input: string; task_id: string; run_id: string }
  | { v: 1; type: "task.regenerate"; index: number; input: string; task_id: string; run_id: string }
  | { v: 1; type: "share.export"; path: string; content: string; count: number }
  | { v: 1; type: "config.get" }
  | { v: 1; type: "config.set"; patch: Record<string, unknown> }
  | { v: 1; type: "approval.reply"; task_id: string; run_id: string; allow: boolean }
  | { v: 1; type: "clarify.reply"; task_id: string; run_id: string; answer: string }
  | { v: 1; type: "shutdown" };
