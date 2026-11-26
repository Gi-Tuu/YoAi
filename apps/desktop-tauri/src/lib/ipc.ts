/** IPC 客户端：封装 Tauri 命令，维护去重与事件订阅。
 *  后台接收与前台渲染分离：所有消息先进队列，按帧批量 flush 给订阅者。 */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { Command, RuntimeMsg } from "../types/ipc";
import { PROTOCOL_VERSION } from "../types/ipc";

type Listener = (msg: RuntimeMsg) => void;

export class IpcClient {
  private listeners = new Set<Listener>();
  private seen = new Set<string>();        // task_id:run_id:seq 去重
  private queue: RuntimeMsg[] = [];
  private flushScheduled = false;
  private unlisten: (() => void) | null = null;
  connected = false;

  /** 订阅 Tauri 发出的 runtime 消息。 */
  async connect(): Promise<void> {
    if (this.unlisten) return;
    this.unlisten = await listen<RuntimeMsg>("runtime://message", (e) => {
      this.enqueue(e.payload);
    });
    await this.send({ v: PROTOCOL_VERSION, type: "hello", client: "tauri", protocol: PROTOCOL_VERSION });
    this.connected = true;
  }

  disconnect(): void {
    this.unlisten?.();
    this.unlisten = null;
    this.connected = false;
    this.queue = [];
  }

  onMessage(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** 入队 + 去重；requestAnimationFrame 批量 flush（降低高频状态更新成本，
   *  但下一帧必出，首个可见更新不被长时间缓存）。 */
  private enqueue(msg: RuntimeMsg): void {
    if (msg.task_id && msg.run_id && typeof msg.seq === "number" && msg.seq >= 0) {
      const key = `${msg.task_id}:${msg.run_id}:${msg.seq}`;
      if (this.seen.has(key)) return;
      this.seen.add(key);
      // 防止无限增长：每个 run 保留最近 20000 个 key 足够
      if (this.seen.size > 100000) this.seen.clear();
    }
    this.queue.push(msg);
    // 流式 delta/thinking 立即上屏（逐 token 可见）；其他高频事件走 rAF 批量。
    if ((msg as { type?: string; event?: string }).type === "event" &&
        ["delta", "thinking"].includes((msg as { event?: string }).event ?? "")) {
      this.flushNow();
      return;
    }
    if (this.flushScheduled) return;
    this.flushScheduled = true;
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(this.flushNow);
    else setTimeout(this.flushNow, 0);
  }

  private flushNow = (): void => {
    this.flushScheduled = false;
    const batch = this.queue;
    this.queue = [];
    for (const m of batch) for (const l of this.listeners) l(m);
  };

  /** 直接喂一条消息（测试/模拟用，跳过 Tauri 传输）。 */
  inject(msg: RuntimeMsg): void {
    this.enqueue(msg);
  }

  async send(cmd: Command): Promise<void> {
    // Rust 侧命令名 = ipc_send，payload 为 JSON 字符串
    await invoke("ipc_send", { json: JSON.stringify(cmd) });
  }

  async startTask(taskId: string, runId: string, input: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "task.start", task_id: taskId, run_id: runId, input });
  }

  async cancelTask(taskId: string, runId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "task.cancel", task_id: taskId, run_id: runId });
  }

  async replyApproval(taskId: string, runId: string, allow: boolean): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "approval.reply", task_id: taskId, run_id: runId, allow });
  }

  // ---- v1 扩展：会话管理 ----
  async refreshSession(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "session.state" });
  }
  async createSession(name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "session.create", name });
  }
  async switchSession(sessionId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "session.switch", session_id: sessionId });
  }
  async renameSession(sessionId: string, name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "session.rename", session_id: sessionId, name });
  }
  async deleteSession(sessionId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "session.delete", session_id: sessionId });
  }

  // ---- v1 扩展：通讯 ----
  async chatState(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "chat.state" });
  }
  async chatHistory(target: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "chat.history", target });
  }
  async chatSend(target: string, text: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "chat.send", target, text });
  }
  async chatNewGroup(name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "chat.new_group", name });
  }
  async chatAddMember(target: string, peerId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "chat.add_member", target, peer_id: peerId });
  }
  async chatAddExternal(target: string, name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "chat.add_external", target, name });
  }

  // ---- v1 扩展：星图 ----
  async getArchive(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "archive.get" });
  }

  // ---- v1 扩展：权限档位 ----
  async getPermission(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "permission.get" });
  }
  async setPermission(level: "full" | "smart" | "manual"): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "permission.set", level });
  }

  // ---- 项目模式 ----
  async createProject(name: string, path: string, sessionName?: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "project.create", name, path, session_name: sessionName });
  }
  async listProjects(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "project.list" });
  }
  async deleteProject(projectId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "project.delete", project_id: projectId });
  }
  async newSessionInProject(projectId: string, name?: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "session.new_in_project", project_id: projectId, name });
  }

  // ---- 右侧工具面板 ----
  /** 内嵌 iframe 被站点拒绝时的兜底：runtime 校验协议后交系统浏览器。 */
  async openExternal(url: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "browser.open", url });
  }
  async listFiles(path: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "fs.list", path });
  }
  async readFile(path: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "fs.read", path });
  }

  // ---- 附件 / 消息动作 / 分享 ----
  async prepareAttachment(path: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "attachment.prepare", path });
  }
  async removeAttachment(id: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "attachment.remove", id });
  }
  async retractMessage(index: number): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "message.retract", index });
  }
  async editMessage(index: number, input: string, taskId: string, runId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "message.edit", index, input,
      task_id: taskId, run_id: runId });
  }
  async regenerate(index: number, input: string, taskId: string, runId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "task.regenerate", index, input,
      task_id: taskId, run_id: runId });
  }
  async shareExport(path: string, content: string, count: number): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "share.export", path, content, count });
  }
  /** R0：只记录用户动作，不触发进化。 */
  async recordFeedback(kind: string, task: string, runId: string, note = ""): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "feedback.record", kind, task,
      run_id: runId, note });
  }
  async getBoundary(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "boundary.get" });
  }
  async triggerRsi(tags: string[] = []): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.trigger", tags });
  }
  async validateCandidate(nodeId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.validate", node_id: nodeId });
  }
  async startTrial(nodeId: string, scope: string, maxN = 20): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.trial_start",
      node_id: nodeId, scope, max_n: maxN });
  }
  async stopTrial(trialId: string, reason = ""): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.trial_stop",
      trial_id: trialId, reason });
  }
  async trialReport(trialId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.trial_report", trial_id: trialId });
  }
  async approveActive(trialId: string, approvedBy: string, reason = ""): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.promote_active",
      trial_id: trialId, approved_by: approvedBy, reason });
  }
  async rejectTrial(trialId: string, reason = ""): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.reject", trial_id: trialId, reason });
  }
  async checkRollback(nodeId: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "rsi.rollback", node_id: nodeId });
  }
  async getMcpStatus(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "mcp.status" });
  }
  async getMcpConfig(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "mcp.config_get" });
  }
  async setMcpConfig(text: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "mcp.config_set", text });
  }
  async reloadMcp(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "mcp.reload" });
  }
  async getSkillStatus(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.status" });
  }
  async getSkillConfig(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.config_get" });
  }
  async setSkillConfig(text: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.config_set", text });
  }
  async reloadSkills(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.reload" });
  }
  async generateSkillRequirements(name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.requirements_generate", name });
  }
  async generateSkillLock(name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.lock_generate", name });
  }
  async getSkillMarket(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.market_list" });
  }
  async addRemoteSkillMarket(url: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.market_add_remote", url });
  }
  async refreshRemoteSkillMarket(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.market_refresh_remote" });
  }
  async addSkillMarket(source: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.market_add", source });
  }
  async installMarketSkill(name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.market_install", name });
  }
  async publishMarketSkill(name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.market_publish", name });
  }
  async removeMarketSkill(name: string): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "skill.market_remove", name });
  }

  async shutdown(): Promise<void> {
    await this.send({ v: PROTOCOL_VERSION, type: "shutdown" });
    this.disconnect();
  }
}

export const ipc = new IpcClient();
