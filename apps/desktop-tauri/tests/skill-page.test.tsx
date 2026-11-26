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
    const install = vi.spyOn(ipc, "installMarketSkill").mockResolvedValue();
    const verifyCt = vi.spyOn(ipc, "verifySkillCt").mockResolvedValue();
    const anchorCt = vi.spyOn(ipc, "anchorSkillCt").mockResolvedValue();
    render(<SkillPage />);
    await act(async () => {
      ipc.inject({ v: 1, type: "skill.state", status: {
        config: "cfg",
        skills: [{ name: "research", description: "调研", prompt: "先列主题", tools: ["web_search"],
          enforce_tools: false, scripts: [], resources: [] }],
        dependencies: { research: { requirements: "req", requirements_exists: true,
          lock: "lock", lock_exists: false, venv: "venv", venv_exists: false, inline: [] } },
        tools: ["skill_load", "skill_list", "skill_run", "skill_resource_read"],
      } });
      ipc.inject({ v: 1, type: "skill.config", text: '{"skills": []}' });
      ipc.inject({ v: 1, type: "skill.market.state", status: {
        catalog: "catalog", packages_dir: "pkgs", sources: [],
        transparency: { path: "ct.jsonl", entries: 2, valid: true },
        items: [{ name: "market-demo", version: "1.0", description: "市场技能",
          source: "source", source_type: "remote", lock_exists: true,
          package_sha256: "abcdef0123456789", ct_url: "http://127.0.0.1/ct",
          ct_receipt_hash: "1122334455667788" }],
      } });
      await new Promise((r) => setTimeout(r, 50));
    });
    await waitFor(() => expect(screen.getByText("research")).toBeTruthy());
    expect(screen.getByText("skill_load")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("技能配置"), { target: { value: '{"skills": [1]}' } });
    fireEvent.click(screen.getByText("保存并重载"));
    expect(setConfig).toHaveBeenCalledWith('{"skills": [1]}');
    expect(screen.getByText("market-demo")).toBeTruthy();
    const installButton = screen.getAllByText("安装")[0];
    if (!installButton) throw new Error("install button missing");
    fireEvent.click(installButton);
    expect(install).toHaveBeenCalledWith("market-demo");

    expect(screen.getByText(/本地透明日志：2 条/)).toBeTruthy();
    fireEvent.click(screen.getByText("校验远端 CT"));
    expect(verifyCt).toHaveBeenCalledWith("market-demo");
    fireEvent.click(screen.getByText("锚定到远端 CT"));
    expect(anchorCt).toHaveBeenCalledWith("market-demo");
    await act(async () => {
      ipc.inject({ v: 1, type: "skill.ct.result", result: {
        ok: true, action: "verify", name: "market-demo",
        reason: "CT 回执有效", sha256: "abcdef0123456789",
        ct_url: "http://127.0.0.1/ct", receipt_hash: "1122334455667788",
      } });
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText(/CT 校验：通过/)).toBeTruthy();
  });
});
