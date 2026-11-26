/** R1 看板回归：收到 boundary.state 后显示总览与能力标签表。 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, act, waitFor, fireEvent } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => {}) }));

import { BoundaryPage } from "../src/components/BoundaryPage";
import { ipc } from "../src/lib/ipc";
import type { BoundaryStateMsg } from "../src/types/ipc";

const state: BoundaryStateMsg = {
  v: 1, type: "boundary.state",
  report: {
    window_days: 30, total: 6, success: 4, success_rate: 0.6667,
    rework: 2, rework_rate: 0.3333,
    rows: [{ tag: "temporal", total: 20, success: 12, success_rate: 0.6,
      success_ci: [0.39, 0.78], rework: 5, rework_rate: 0.25,
      avg_tokens: 12000, positive: 1, baseline_gap: -0.1,
      status: "weak", sample_enough: true }],
  },
};

describe("能力边界看板", () => {
  it("展示总览卡片、状态色标与 Wilson 区间，并可对薄弱边界触发 shadow 候选", async () => {
    const trigger = vi.spyOn(ipc, "triggerRsi").mockResolvedValue();
    render(<BoundaryPage />);
    await act(async () => {
      ipc.inject(state);
      await new Promise((r) => setTimeout(r, 50));
    });
    await waitFor(() => expect(screen.getByText("能力边界看板")).toBeTruthy());
    expect(screen.getByText("66.7%")).toBeTruthy();
    expect(screen.getByText("temporal")).toBeTruthy();
    expect(screen.getByText("薄弱")).toBeTruthy();
    expect(screen.getByText(/39.0%/)).toBeTruthy();
    expect(screen.getByText("12,000")).toBeTruthy();
    fireEvent.click(screen.getByText("生成候选"));
    expect(trigger).toHaveBeenCalledWith(["temporal"]);
  });
});
