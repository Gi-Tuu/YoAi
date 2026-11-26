/** R4 元策略页回归：版本展示、提案与批准。 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => {}) }));

import { MetaPage } from "../src/components/MetaPage";
import { ipc } from "../src/lib/ipc";

describe("元策略页", () => {
  it("显示版本并可生成提案/批准", async () => {
    const propose = vi.spyOn(ipc, "proposeMetaPolicy").mockResolvedValue();
    const approve = vi.spyOn(ipc, "approveMetaPolicy").mockResolvedValue();
    render(<MetaPage />);
    await act(async () => {
      ipc.inject({ v: 1, type: "rsi.meta.state", status: {
        active: { version: 1, min_trial_samples: 20 },
        versions: [{ version: 1, reason: "初始" }, { version: 2, reason: "候选" }],
      } });
      await new Promise((r) => setTimeout(r, 50));
    });
    await waitFor(() => expect(screen.getByText("当前生效：v1")).toBeTruthy());
    fireEvent.click(screen.getByText("生成候选提案"));
    expect(propose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("批准此版本"));
    expect(approve).toHaveBeenCalledWith(2);
  });
});
