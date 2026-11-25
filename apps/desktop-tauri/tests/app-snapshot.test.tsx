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
    expect(screen.getByText(/主题偏好/)).toBeTruthy();
  });
});
