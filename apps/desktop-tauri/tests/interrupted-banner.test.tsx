/** 被打断的对话横幅（S5-2）回归。 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { InterruptedBanner } from "../src/components/InterruptedBanner";
import type { InterruptedTurn } from "../src/types/ipc";

function item(over: Partial<InterruptedTurn> = {}): InterruptedTurn {
  return {
    run_id: "r1", task_id: "t1", session_id: "s1", session_name: "新会话",
    input: "写一份周报", truncated: false, started_at: "2026-11-27T10:00:00+08:00", ...over,
  };
}

function setup(items: InterruptedTurn[], current = "s1", busy = false) {
  const onResend = vi.fn(); const onSwitch = vi.fn(); const onDismiss = vi.fn();
  render(<InterruptedBanner items={items} currentSessionId={current} busy={busy}
                            onResend={onResend} onSwitch={onSwitch} onDismiss={onDismiss} />);
  return { onResend, onSwitch, onDismiss };
}

afterEach(() => cleanup());

describe("被打断的对话横幅", () => {
  it("没有记录时什么都不渲染", () => {
    const { container } = render(<InterruptedBanner items={[]} currentSessionId="s1" busy={false}
      onResend={() => {}} onSwitch={() => {}} onDismiss={() => {}} />);
    expect(container.innerHTML).toBe("");
  });

  it("同一会话：重新发送用原输入；忽略发出 run_id", () => {
    const { onResend, onDismiss } = setup([item()]);
    expect(screen.getByText("「写一份周报」")).toBeTruthy();
    fireEvent.click(screen.getByText("重新发送"));
    expect(onResend).toHaveBeenCalledWith(expect.objectContaining({ run_id: "r1", input: "写一份周报" }));
    fireEvent.click(screen.getByText("忽略"));
    expect(onDismiss).toHaveBeenCalledWith("r1");
  });

  it("别的会话：先切过去，不直接重发", () => {
    const { onSwitch, onResend } = setup([item({ session_id: "s2", session_name: "项目会话" })]);
    expect(screen.queryByText("重新发送")).toBeNull();
    fireEvent.click(screen.getByText("切到「项目会话」"));
    expect(onSwitch).toHaveBeenCalledWith("s2");
    expect(onResend).not.toHaveBeenCalled();
  });

  it("正在对话时不能重发；内容被截断时只能忽略", () => {
    setup([item()], "s1", true);
    expect((screen.getByText("重新发送") as HTMLButtonElement).disabled).toBe(true);
    cleanup();
    setup([item({ truncated: true })]);
    expect(screen.queryByText("重新发送")).toBeNull();
    expect(screen.getByText("内容太长，请手动重新发送")).toBeTruthy();
  });

  it("最多显示 3 条，长输入只显示开头", () => {
    const many = [1, 2, 3, 4].map((i) => item({ run_id: `r${i}`, input: `${"很长".repeat(40)}${i}` }));
    setup(many);
    expect(screen.getAllByText("忽略")).toHaveLength(3);
    expect(screen.getAllByText(/…」$/)).toHaveLength(3);
  });
});
