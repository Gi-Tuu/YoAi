/** 星图进化审计链回归：节点详情要显示晋升结论、样本量与父子区间。 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => {}),
}));

import { GalaxyPage } from "../src/components/GalaxyPage";
import { ipc } from "../src/lib/ipc";
import type { ArchiveStateMsg } from "../src/types/ipc";

const state: ArchiveStateMsg = {
  v: 1, type: "archive.state",
  nodes: [{
    id: "n1", name: "memory_expert", lifecycle: "active", version: 2,
    parent_id: "p1", depth: 1, capability_tags: ["memory"], tools: ["events_between"],
    strategy_bias: "direct", model_tier: "standard", diff: "{}",
    evidence_count: 1, created_at: "2026-11-26T00:00:00Z", prompt_suffix: "擅长时间推理",
    evidence: [{ id: "e1", kind: "trial", task_fingerprint: "f1", outcome: "pass",
      detail: "", created_at: "2026-11-26T00:00:00Z" }],
    reports: [{
      id: "rep1", evidence_id: "e1", triggered: true, cause: "capability",
      new_node_id: "n1", reason: "候选已创建", created_at: "2026-11-26T00:00:00Z",
      promotion: { promoted: true, reason: "隔离评测 improved", report: {
        verdict: "improved", note: "优于父节点", total_samples: 5,
        boundaries: [{ capability_tag: "memory", node_rate: 0.8, parent_rate: 0.5,
          node_ci: [0.4, 0.95], parent_ci: [0.2, 0.8], sample_enough: true }],
      } },
    }],
  }],
};

describe("星图进化审计", () => {
  it("点击节点显示进化报告与父子区间", async () => {
    render(<GalaxyPage />);
    await act(async () => {
      ipc.inject(state);
      await new Promise((r) => setTimeout(r, 50));
    });
    fireEvent.click(screen.getByText("memory_expert"));
    await waitFor(() => expect(screen.getByText("进化审计")).toBeTruthy());
    expect(screen.getByText(/隔离评测 improved/)).toBeTruthy();
    expect(screen.getByText(/样本 5/)).toBeTruthy();
    expect(screen.getByText(/父 0.50/)).toBeTruthy();
    expect(screen.getByText(/证据索引/)).toBeTruthy();
  });
});
