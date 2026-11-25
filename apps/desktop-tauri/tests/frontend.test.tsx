/** 前端回归测试：事件去重、过程行渲染、流式碎片合并（性能相关用数据量断言）。 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ProcessPanel } from "../src/components/ProcessPanel";
import type { ProcEvent } from "../src/hooks/useTaskStream";

// Tauri API 在 jsdom 下不可用，ipc 模块在组件测试里不需要连接
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));

describe("ProcessPanel", () => {
  const mk = (n: number): ProcEvent[] =>
    Array.from({ length: n }, (_, i) => ({
      seq: i, name: i % 2 ? "tool_result" : "tool_call",
      data: { tool: `tool_${i}` }, at: i,
    }));

  it("默认折叠：只显示摘要，完全隐藏记录", () => {
    const { container } = render(<ProcessPanel events={mk(10000)} thinking="" />);
    expect(screen.getByText(/10000 条记录/)).toBeTruthy();
    expect(container.querySelectorAll(".proc-row")).toHaveLength(0);
  });

  it("思考默认折叠，只留入口", () => {
    render(<ProcessPanel events={[]} thinking="try, I checked facts" />);
    expect(screen.getByText(/查看思考过程/)).toBeTruthy();
    expect(screen.queryByText(/try, I checked/)).toBeNull();
  });

  it("大量标签+内容同行渲染（标签后无块级元素）", () => {
    const events = mk(3);
    const longResult = "长工具结果".repeat(90) + "结尾可见";
    events[1]!.data.result = longResult;
    const { container } = render(<ProcessPanel events={events} thinking="" />);
    const toggle = screen.getByRole("button", { name: /执行过程/ });
    fireEvent.click(toggle);
    expect(container.querySelector(".process-scroll")).toBeNull();
    const rows = container.querySelectorAll(".proc-row");
    expect(rows).toHaveLength(3);
    expect(rows[1]?.textContent).toContain(longResult);
    rows.forEach((row) => {
      expect(row.querySelector(".proc-label")).toBeTruthy();
      expect(row.textContent).toMatch(/\[(调用工具|工具完成)\]/);
    });
    fireEvent.click(toggle);
    expect(container.querySelectorAll(".proc-row")).toHaveLength(0);
  });
});
