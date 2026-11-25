/** 产物/改动卡片回归：图1产物列表、图2改动摘要 + 行级 diff 展开。 */
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Artifacts, Changes } from "../src/components/FileChanges";

const base = {
  id: "c1", at: "2026-11-25T00:00:00Z", session_id: "s1", project_id: "p1", run_id: "r1",
  path: "src/agent.py", action: "patch" as const, added: 2, removed: 1,
  diff: [
    { kind: "context" as const, text: "def f():", old_line: 1, new_line: 1 },
    { kind: "remove" as const, text: "    return 1", old_line: 2 },
    { kind: "add" as const, text: "    return 2", new_line: 2 },
    { kind: "add" as const, text: "    return 3", new_line: 3 },
  ],
};

describe("产物卡片", () => {
  it("新建文件显示为产物，带下载按钮", () => {
    render(<Artifacts records={[{ ...base, action: "create", after: "<html>game</html>" }]} />);
    expect(screen.getByText("agent.py")).toBeTruthy();
    expect(screen.getByTitle("下载产物")).toBeTruthy();
    expect(screen.getByText(/字符/)).toBeTruthy();
  });

  it("无产物时不渲染", () => {
    const { container } = render(<Artifacts records={[]} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("改动摘要 + 行级 diff", () => {
  it("显示 N 个文件已修改 与 +X/-Y 汇总", () => {
    render(<Changes records={[base]} />);
    expect(screen.getByText("1 个文件已修改")).toBeTruthy();
    expect(screen.getByText("+2")).toBeTruthy();
    expect(screen.getByText("-1")).toBeTruthy();
  });

  it("点击文件行展开行级 diff（绿+红-）", () => {
    render(<Changes records={[base]} />);
    fireEvent.click(document.querySelector(".changes-head") as HTMLElement);
    fireEvent.click(document.querySelector(".change-row-head") as HTMLElement);
    expect(screen.getByText("src/agent.py")).toBeTruthy();
    expect(document.querySelectorAll(".diff-add").length).toBe(2);
    expect(document.querySelectorAll(".diff-remove").length).toBe(1);
    expect(screen.getByText(/return 2/)).toBeTruthy();
  });
});
