/** 技能页回归：列表、工具与配置保存。 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => {}) }));

import { SkillPage } from "../src/components/SkillPage";
import { ipc } from "../src/lib/ipc";

describe("技能页", () => {
  it("显示技能并可保存配置", async () => {
    const setConfig = vi.spyOn(ipc, "setSkillConfig").mockResolvedValue();
    render(<SkillPage />);
    await act(async () => {
      ipc.inject({ v: 1, type: "skill.state", status: {
        config: "cfg",
        skills: [{ name: "research", description: "调研", prompt: "先列主题", tools: ["web_search"],
          enforce_tools: false, scripts: [], resources: [] }],
        dependencies: { research: { requirements: "req", requirements_exists: true,
          lock: "lock", lock_exists: false, inline: [] } },
        tools: ["skill_load", "skill_list", "skill_run", "skill_resource_read"],
      } });
      ipc.inject({ v: 1, type: "skill.config", text: '{"skills": []}' });
      await new Promise((r) => setTimeout(r, 50));
    });
    await waitFor(() => expect(screen.getByText("research")).toBeTruthy());
    expect(screen.getByText("skill_load")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("技能配置"), { target: { value: '{"skills": [1]}' } });
    fireEvent.click(screen.getByText("保存并重载"));
    expect(setConfig).toHaveBeenCalledWith('{"skills": [1]}');
  });
});
