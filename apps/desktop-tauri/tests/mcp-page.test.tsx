/** MCP 管理页回归：状态、工具列表与配置编辑。 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => {}) }));

import { McpPage } from "../src/components/McpPage";
import { ipc } from "../src/lib/ipc";

describe("MCP 管理页", () => {
  it("显示 server/tool 状态并保存配置", async () => {
    const setConfig = vi.spyOn(ipc, "setMcpConfig").mockResolvedValue();
    render(<McpPage />);
    await act(async () => {
      ipc.inject({ v: 1, type: "mcp.state", status: {
        config: "cfg", servers: { fake: { running: true, server_info: { name: "fake" }, stderr_tail: [] } },
        tools: ["mcp__fake__echo"],
      } });
      ipc.inject({ v: 1, type: "mcp.config", text: '{"servers": []}' });
      await new Promise((r) => setTimeout(r, 50));
    });
    await waitFor(() => expect(screen.getByText("mcp__fake__echo")).toBeTruthy());
    expect(screen.getByText("运行中")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("MCP 配置"), { target: { value: '{"servers": [1]}' } });
    fireEvent.click(screen.getByText("保存并重载"));
    expect(setConfig).toHaveBeenCalledWith('{"servers": [1]}');
  });
});
