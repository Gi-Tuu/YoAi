/** 消息动作归属回归：用户专有 / 智能体专有 / 两者都有不能混。 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MessageActions } from "../src/components/MessageActions";

describe("消息动作条", () => {
  it("用户消息有编辑/撤回，没有重新生成", () => {
    const onEdit = vi.fn(); const onRetract = vi.fn();
    render(<MessageActions role="user" onCopy={() => {}} onShare={() => {}}
      onEdit={onEdit} onRetract={onRetract} />);
    expect(screen.getByText("编辑")).toBeTruthy();
    expect(screen.getByText("撤回")).toBeTruthy();
    expect(screen.queryByText("重新生成")).toBeNull();
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByText("撤回"));
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onRetract).toHaveBeenCalledTimes(1);
  });

  it("智能体消息有重新生成，没有编辑/撤回", () => {
    const onRegenerate = vi.fn();
    render(<MessageActions role="assistant" onCopy={() => {}} onShare={() => {}}
      onRegenerate={onRegenerate} />);
    expect(screen.getByText("重新生成")).toBeTruthy();
    expect(screen.queryByText("编辑")).toBeNull();
    expect(screen.queryByText("撤回")).toBeNull();
    fireEvent.click(screen.getByText("重新生成"));
    expect(onRegenerate).toHaveBeenCalledTimes(1);
  });

  it("复制与分享两者都有", () => {
    const onCopy = vi.fn(); const onShare = vi.fn();
    render(<MessageActions role="user" onCopy={onCopy} onShare={onShare} />);
    fireEvent.click(screen.getByText("复制"));
    fireEvent.click(screen.getByText("分享"));
    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(onShare).toHaveBeenCalledTimes(1);
  });
});
