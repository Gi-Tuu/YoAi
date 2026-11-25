/** 回归：hello 后的 snapshot 必须驱动会话面板/输入区/侧栏。
 *  定位 GUI 中"ready 到了但快照没加载"的问题。 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";

const listeners: Set<(m: unknown) => void> = new Set();
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (_ev: string, cb: (e: { payload: unknown }) => void) => {
    listeners.add((m) => cb({ payload: m }));
    return () => {};
  }),
}));

import App from "../src/App";
import type { SnapshotMsg } from "../src/types/ipc";

const snap: SnapshotMsg = {
  v: 1, type: "snapshot",
  sessions: [{ id: "s1", name: "测试会话" }],
  current_id: "s1",
  history: [],
  model: "spark-x2.6",
  facts: { "主题偏好": "深色" },
  goals: [],
  write_stats: { events: 2 },
  tools: [],
  thinking_log: [],
};

function emit(m: unknown) { for (const l of listeners) l(m); }

describe("App snapshot 消费", () => {
  beforeEach(() => { listeners.clear(); localStorage.clear(); });

  it("收到 ready + snapshot 后显示会话、输入区和事实", async () => {
    render(<App />);
    // 等 useEffect 注册 listener（listen 是异步 mock）
    await waitFor(() => expect(listeners.size).toBeGreaterThan(0));
    // 模拟 runtime 回复
    await act(async () => {
      emit({ v: 1, type: "ready", protocol: 1, python: "3.13", tools: [], sessions: [], config: {} });
      emit(snap);
      await new Promise((r) => setTimeout(r, 50));  // 等 requestAnimationFrame 批量 flush
    });
    expect(screen.queryByRole("region", { name: "会话" })).toBeNull();
    fireEvent.pointerEnter(screen.getByRole("button", { name: "对话" }));
    const sessions = await screen.findByRole("region", { name: "会话" });
    expect(sessions.querySelector('[aria-current="true"]')?.textContent).toContain("测试会话");
    expect(screen.getByRole("button", { name: /新建/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "重命名 测试会话" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "删除 测试会话" })).toBeTruthy();
    expect(screen.queryByText(/模型 · spark-x2\.6/)).toBeNull();
    expect(screen.queryByText("就绪")).toBeNull();
    expect(screen.queryByText("我的对话")).toBeNull();
    expect(screen.getByRole("button", { name: "对话" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("button", { name: "最小化" })).toBeTruthy();
    const input = screen.getByRole("textbox", { name: "输入任务" });
    const permission = screen.getByRole("combobox", { name: "权限" });
    expect(permission.closest(".composer")).toBe(input.closest(".composer"));
    expect(permission.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText(/主题偏好/)).toBeNull();
    const facts = screen.getByRole("button", { name: /个人事实/ });
    fireEvent.pointerEnter(facts);
    const preview = await screen.findByRole("region", { name: "个人事实" });
    fireEvent.pointerLeave(preview);
    await waitFor(() => expect(screen.queryByText(/主题偏好/)).toBeNull());
    fireEvent.pointerEnter(screen.getByRole("button", { name: /个人事实/ }));
    const factsPanel = await screen.findByRole("region", { name: "个人事实" });
    fireEvent.click(factsPanel);
    fireEvent.pointerLeave(factsPanel);
    expect(screen.getByText(/主题偏好/)).toBeTruthy();
    const memory = screen.getByRole("button", { name: /本轮记忆/ });
    await act(async () => { memory.click(); });
    expect(screen.getByText(/主题偏好/)).toBeTruthy();
    expect(screen.getByText("本轮记忆 +2")).toBeTruthy();
    const memoryPanel = screen.getByRole("region", { name: "本轮记忆" });
    expect(Number(memoryPanel.style.zIndex)).toBeGreaterThan(Number(factsPanel.style.zIndex));
    fireEvent.click(factsPanel);
    expect(Number(factsPanel.style.zIndex)).toBeGreaterThan(Number(memoryPanel.style.zIndex));
    fireEvent.click(screen.getByRole("button", { name: "收起个人事实" }));
    expect(screen.queryByText(/主题偏好/)).toBeNull();
  });
});

describe("历史消息 thinking 显示", () => {
  beforeEach(() => { listeners.clear(); localStorage.clear(); });

  it("snapshot 携带 thinking_log 时历史消息显示可展开入口", async () => {
    const withThink: SnapshotMsg = {
      ...snap,
      history: [
        { role: "user", text: "记住我叫小明" },
        { role: "assistant", text: "好的，已记住。" },
      ],
      thinking_log: [{
        run_id: "r1", session_id: "s1", at: "2026-11-25T12:00:00",
        text: "用户说叫小明，应当写入事实", input: "记住我叫小明",
      }],
    };
    render(<App />);
    await waitFor(() => expect(listeners.size).toBeGreaterThan(0));
    await act(async () => {
      emit({ v: 1, type: "ready", protocol: 1, python: "3.13", tools: [], sessions: [], config: {} });
      emit(withThink);
      await new Promise((r) => setTimeout(r, 50));
    });
    const link = screen.getByText(/查看思考过程/);
    expect(link).toBeTruthy();
    // 默认折叠，点开展示正文
    await act(async () => { (link as HTMLElement).click(); await new Promise((r) => setTimeout(r, 30)); });
    expect(screen.getByText(/用户说叫小明/)).toBeTruthy();
  });
});

describe("审批弹窗交互（hook 级）", () => {
  it("clearApproval 清除审批状态（点击后消失的数据层保证）", async () => {
    // useTaskStream 的 clearApproval 是点击后消失的核心保证；
    // 组件接线在 App.tsx onApproval 回调里（clearApproval → replyApproval）
    const { renderHook, act } = await import("@testing-library/react");
    const { useTaskStream } = await import("../src/hooks/useTaskStream");
    const msgs = [{
      v: 1, type: "approval.request", task_id: "t1", run_id: "r1", seq: 1,
      tool: "request_capability", question: "确认执行?", detail: "{}",
    }];
    const { result } = renderHook(() => useTaskStream(msgs as never));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(result.current.runs.get("r1")?.approval?.tool).toBe("request_capability");
    await act(async () => { result.current.clearApproval("r1"); });
    expect(result.current.runs.get("r1")?.approval).toBeNull();
  });
});

describe("项目模式 UI", () => {
  it("项目列表与创建入口渲染；项目会话显示当前项目", async () => {
    const { ProjectPanel } = await import("../src/components/ProjectPanel");
    const projects = [{ id: "p1", name: "我的项目", path: "C:/proj", created_at: "" }];
    const sessions = [{ id: "s1", name: "会话1", mode: "project" as const, project_id: "p1" }];
    render(<ProjectPanel projects={projects} sessions={sessions}
           currentSessionId="s1" ready={true} busy={false} onError={() => {}} />);
    expect(screen.getByText("我的项目")).toBeTruthy();
    expect(screen.getByText(/当前：我的项目/)).toBeTruthy();
    expect(screen.getByText("＋ 创建项目")).toBeTruthy();
  });

  it("聊天模式会话不显示当前项目条", async () => {
    const { ProjectPanel } = await import("../src/components/ProjectPanel");
    const sessions = [{ id: "s1", name: "会话1", mode: "chat" as const }];
    render(<ProjectPanel projects={[]} sessions={sessions}
           currentSessionId="s1" ready={true} busy={false} onError={() => {}} />);
    expect(screen.queryByText(/当前：/)).toBeNull();
    expect(screen.getByText(/暂无项目/)).toBeTruthy();
  });
});
