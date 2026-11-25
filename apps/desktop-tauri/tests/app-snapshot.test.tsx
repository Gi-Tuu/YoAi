/** 回归：hello 后的 snapshot 必须驱动会话选择器/模型 chip/侧栏。
 *  定位 GUI 中"ready 到了但快照没加载"的问题。 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

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

  it("收到 ready + snapshot 后显示会话名、模型名、事实", async () => {
    render(<App />);
    // 等 useEffect 注册 listener（listen 是异步 mock）
    await waitFor(() => expect(listeners.size).toBeGreaterThan(0));
    // 模拟 runtime 回复
    await act(async () => {
      emit({ v: 1, type: "ready", protocol: 1, python: "3.13", tools: [], sessions: [], config: {} });
      emit(snap);
      await new Promise((r) => setTimeout(r, 50));  // 等 requestAnimationFrame 批量 flush
    });
    await waitFor(() => {
      expect(screen.getByTitle("切换会话")).toBeTruthy();
    });
    const select = screen.getByTitle("切换会话") as HTMLSelectElement;
    expect(select.value).toBe("s1");
    expect(select.options[0]?.text).toContain("测试会话");
    expect(screen.getAllByText(/spark-x2\.6/).length).toBeGreaterThan(0);
    // 事实不再常驻侧栏，而是右侧锚点方块（悬停才展开）；角标显示数量
    expect(screen.getByTitle("个人事实 · 1")).toBeTruthy();
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
