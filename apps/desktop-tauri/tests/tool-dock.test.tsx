/** 右侧工具方格回归：浏览器 / 终端 / 查看文件三格都能点开并可用。 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => {}) }));

import { ToolDock } from "../src/components/ToolDock";
import { ipc } from "../src/lib/ipc";
import type { RunState } from "../src/hooks/useTaskStream";
import type { FileTreeMsg } from "../src/types/ipc";

afterEach(() => vi.restoreAllMocks());

const doneRun: RunState = {
  taskId: "t1", runId: "r1", input: "test", state: "done", detail: "",
  events: [{ seq: 0, name: "tool_result", data: { tool: "shell_run", result: "命令输出 ok" }, at: 0 }],
  streamText: new Map(), thinking: "", finalText: "", approval: null,
  fileChanges: [], startedAt: 0,
};

function tile(name: string): HTMLElement {
  const el = screen.getByText(name).closest("button");
  if (!el) throw new Error(`找不到方格：${name}`);
  return el;
}

describe("右侧工具方格", () => {
  it("工具和资料共用一列，终端悬停、固定后可正常执行", async () => {
    const onRunCommand = vi.fn((_command: string) => "r1");
    render(<ToolDock runs={new Map([["r1", doneRun]])} ready onRunCommand={onRunCommand} />);
    expect(tile("浏览器")).toBeTruthy();
    expect(tile("终端")).toBeTruthy();
    expect(tile("查看文件")).toBeTruthy();

    const terminalTile = tile("终端");
    expect(terminalTile.parentElement).toBe(tile("个人事实").parentElement);
    fireEvent.pointerEnter(terminalTile);
    const preview = await screen.findByRole("region", { name: "终端" });
    fireEvent.pointerLeave(preview);
    await waitFor(() => expect(screen.queryByRole("region", { name: "终端" })).toBeNull());
    fireEvent.pointerEnter(tile("终端"));
    const pinned = await screen.findByRole("region", { name: "终端" });
    fireEvent.click(pinned);
    fireEvent.pointerLeave(pinned);
    expect(screen.getByRole("button", { name: "收起终端" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("命令"), { target: { value: "dir" } });
    fireEvent.click(screen.getByRole("button", { name: "执行" }));

    expect(onRunCommand).toHaveBeenCalledTimes(1);
    const submitted = String(onRunCommand.mock.calls[0]?.[0] ?? "");
    expect(submitted).toContain("shell_run");
    expect(submitted).toContain("dir");
    expect(screen.getByText("命令输出 ok")).toBeTruthy();
  });

  it("查看文件拉目录树，点文件显示内容预览", async () => {
    const listSpy = vi.spyOn(ipc, "listFiles").mockResolvedValue();
    const readSpy = vi.spyOn(ipc, "readFile").mockResolvedValue();
    render(<ToolDock runs={new Map()} ready onRunCommand={() => "r1"} />);

    fireEvent.click(tile("查看文件"));
    await waitFor(() => expect(listSpy).toHaveBeenCalledWith(""));

    const tree: FileTreeMsg = {
      v: 1, type: "file.tree", root: "/work", label: "工作区", path: "",
      entries: [{ name: "a.txt", path: "a.txt", is_dir: false }],
    };
    await act(async () => {
      ipc.inject(tree);
      await new Promise((r) => setTimeout(r, 50));
    });
    fireEvent.click(screen.getByText("a.txt"));
    expect(readSpy).toHaveBeenCalledWith("a.txt");

    await act(async () => {
      ipc.inject({ v: 1, type: "file.content", root: "/work", path: "a.txt",
        content: "文件内容", size: 4, truncated: false });
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText("文件内容")).toBeTruthy();
  });

  it("浏览器内嵌网址，系统打开交给 runtime 校验", () => {
    const openSpy = vi.spyOn(ipc, "openExternal").mockResolvedValue();
    render(<ToolDock runs={new Map()} ready onRunCommand={() => "r1"} />);
    fireEvent.click(tile("浏览器"));
    fireEvent.change(screen.getByLabelText("网址"), {
      target: { value: "https://example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "打开" }));
    expect(screen.getByTitle("内置浏览器").getAttribute("src")).toBe("https://example.com/");

    fireEvent.click(screen.getByRole("button", { name: "系统打开" }));
    expect(openSpy).toHaveBeenCalledWith("https://example.com/");
  });
});
