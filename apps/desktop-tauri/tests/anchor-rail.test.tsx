/** 锚点交互回归：以自身为中心展开 + 边缘自适应 + 钉住。
 *  定位纯函数覆盖几何，组件测试覆盖 hover 开合与钉住调用。 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { computeAnchorPosition, AnchorRail } from "../src/components/AnchorRail";
import type { SnapshotMsg } from "../src/types/ipc";

const { invokeMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(async (_cmd: string, _args?: unknown) => {}),
}));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

const vp = { width: 1100, height: 760 };

describe("computeAnchorPosition 边缘自适应", () => {
  it("无对话区时以锚点中心展开", () => {
    const p = computeAnchorPosition(
      { left: 1030, top: 300, width: 34, height: 34 },
      { width: 300, height: 220 }, vp, null,
    );
    expect(p.side).toBe("center");
    expect(p.left).toBe(vp.width - 300 - 10);  // 钳制到右边缘内
    expect(p.top).toBe(300 + 17 - 110);
  });

  it("与对话区重叠过半时改到空间更大的一侧", () => {
    // 锚点靠右（x=900），对话区占中间，右侧只剩 ~156px、左侧有 ~890px → 改向 left
    const p = computeAnchorPosition(
      { left: 900, top: 300, width: 34, height: 34 },
      { width: 300, height: 220 }, vp,
      { left: 150, top: 100, width: 780, height: 500 },
    );
    expect(p.side).toBe("left");
    expect(p.left).toBe(900 - 300 - 4);
  });

  it("垂直方向钳制在窗口内", () => {
    const p = computeAnchorPosition(
      { left: 800, top: 700, width: 34, height: 34 },
      { width: 300, height: 220 }, vp, null,
    );
    expect(p.top).toBe(vp.height - 220 - 10);
  });
});

const snap: SnapshotMsg = {
  v: 1, type: "snapshot", sessions: [], current_id: "", history: [], model: "test",
  facts: { "主题偏好": "深色" }, goals: [], write_stats: { events: 1 }, tools: [], thinking_log: [],
};

describe("AnchorRail 锚点交互", () => {
  beforeEach(() => { invokeMock.mockClear(); });

  it("三个锚点渲染且带数量角标，默认不展开内容", () => {
    render(<AnchorRail snap={snap} />);
    expect(screen.getByTitle("个人事实 · 1")).toBeTruthy();
    expect(screen.getByTitle("本轮记忆 · 1")).toBeTruthy();
    expect(screen.queryByText("主题偏好")).toBeNull();  // 未悬停不显示
  });

  it("悬停展开内容，点击钉住调用原生窗口命令", async () => {
    render(<AnchorRail snap={snap} />);
    const tile = screen.getByTitle("个人事实 · 1");
    fireEvent.mouseEnter(tile);
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    expect(screen.getByText("主题偏好")).toBeTruthy();
    const pin = screen.getByTitle("钉住为桌面浮窗");
    fireEvent.click(pin);
    expect(invokeMock).toHaveBeenCalledWith("open_float_panel", { kind: "facts", title: "个人事实" });
  });
});
