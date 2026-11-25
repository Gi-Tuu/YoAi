/** 锚点交互回归：悬停即出原生浮窗（跨窗口 hover 协调）+ 钉住。
 *  这里测主窗口侧命令调用与浮窗侧事件响应；几何/Rust 定位由真机验收。 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { AnchorRail, FloatPanel } from "../src/components/AnchorRail";

const { invokeMock, listeners } = vi.hoisted(() => ({
  invokeMock: vi.fn(async (_cmd: string, _args?: unknown) => {}),
  listeners: new Map<string, Set<(e: { payload: unknown }) => void>>(),
}));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (ev: string, cb: (e: { payload: unknown }) => void) => {
    if (!listeners.has(ev)) listeners.set(ev, new Set());
    listeners.get(ev)!.add(cb);
    return () => { listeners.get(ev)?.delete(cb); };
  }),
}));

function emit(ev: string, payload: unknown) {
  for (const l of listeners.get(ev) ?? []) l({ payload });
}

describe("AnchorRail 悬停出原生窗", () => {
  beforeEach(() => { invokeMock.mockClear(); listeners.clear(); });

  it("三个锚点渲染且带数量角标，默认不显示内容", () => {
    render(<AnchorRail snap={null} />);
    expect(screen.getByTitle("个人事实 · 0")).toBeTruthy();
    expect(screen.getByTitle("长期目标 · 0")).toBeTruthy();
    expect(screen.getByTitle("本轮记忆 · 0")).toBeTruthy();
    expect(screen.queryByText("还没有个人事实。")).toBeNull();
  });

  it("悬停方块调用 hover_float_panel（带锚点屏幕坐标），并广播进入信号", async () => {
    render(<AnchorRail snap={null} />);
    fireEvent.mouseEnter(screen.getByTitle("个人事实 · 0"));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(invokeMock).toHaveBeenCalledWith("hover_float_panel",
      expect.objectContaining({ kind: "facts", title: "个人事实" }));
    expect(invokeMock).toHaveBeenCalledWith("float_hover_signal", { kind: "facts", entering: true });
  });
});

describe("FloatPanel 跨窗口 hover 协调", () => {
  beforeEach(() => { invokeMock.mockClear(); listeners.clear(); });

  it("锚点进入时取消自动关闭，锚点离开后 250ms 收起", async () => {
    render(<FloatPanel kind="facts" title="个人事实" />);
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
    // 等两个 listener 都注册好（动态 import）
    await act(async () => { emit("float://hover-signal", { kind: "facts", entering: true }); });
    // 锚点进入 → 不关
    await act(async () => { emit("float://hover-signal", { kind: "facts", entering: true }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 400)); });
    expect(invokeMock).not.toHaveBeenCalledWith("close_float_panel", expect.anything());
    // 锚点离开 → 250ms 后关
    await act(async () => {
      emit("float://hover-signal", { kind: "facts", entering: false });
      await new Promise((r) => setTimeout(r, 350));
    });
    expect(invokeMock).toHaveBeenCalledWith("close_float_panel", { label: "float-facts" });
  });

  it("点击内容区钉住后，离开不再自动收起", async () => {
    render(<FloatPanel kind="goals" title="长期目标" />);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    fireEvent.click(document.querySelector(".float-body")!);
    expect(screen.getByText(/已钉住/)).toBeTruthy();
    await act(async () => {
      emit("float://hover-signal", { kind: "goals", entering: false });
      await new Promise((r) => setTimeout(r, 400));
    });
    expect(invokeMock).not.toHaveBeenCalledWith("close_float_panel", expect.anything());
  });
});
