/** 定时任务页（S4）回归：协议消息驱动列表 / 横幅 / 运行记录，按钮发出正确命令。 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor, cleanup } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => {}) }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => {}) }));

import { SchedulerPage, draftFromForm, localInputToIso, isoToLocalInput } from "../src/components/SchedulerPage";
import { ipc } from "../src/lib/ipc";
import type { RuntimeMsg, ScheduleJob, ScheduleRun } from "../src/types/ipc";

function job(over: Partial<ScheduleJob> = {}): ScheduleJob {
  return {
    id: "j1", name: "早间回顾", prompt: "列出我进行中的目标",
    trigger: { kind: "daily", time: "09:00" }, enabled: true, allowed_tools: [],
    misfire: "run_once", on_interrupt: "notify", timeout_s: 600, active_hours: "",
    idle_only: true, scratch: null, skip_if_scratch_empty: true,
    next_fire_at: "2026-11-28T09:00:00+08:00", last_run_id: "", last_state: "",
    consecutive_failures: 0, disabled_reason: "", created_by: "user",
    created_at: "2026-11-27T10:00:00+08:00", updated_at: "2026-11-27T10:00:00+08:00",
    schedule_text: "每天 09:00", running: false, waiting: false, ...over,
  };
}

function run(over: Partial<ScheduleRun> = {}): ScheduleRun {
  return {
    run_id: "sch-1", job_id: "j1", job_name: "早间回顾", reason: "schedule", state: "ok",
    started_at: "2026-11-27T09:00:00+08:00", finished_at: "2026-11-27T09:00:07+08:00",
    summary: "有 2 个进行中的目标", quiet: false, denied_tools: [], evidence_id: "", ...over,
  };
}

async function feed(...msgs: RuntimeMsg[]) {
  await act(async () => {
    for (const m of msgs) ipc.inject(m);
    await new Promise((r) => setTimeout(r, 30));
  });
}

const state = (enabled: boolean, jobs: ScheduleJob[]): RuntimeMsg => ({
  v: 1, type: "schedule.state", enabled, jobs, session_id: enabled ? "s9" : "", session_name: "⏰ 定时任务",
});

beforeEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("定时任务页", () => {
  it("未开启时显示横幅，只读展示任务，写操作禁用", async () => {
    render(<SchedulerPage />);
    await feed(state(false, [job()]));
    expect(screen.getByRole("status").textContent).toContain("YOAI_SCHEDULER=0");
    expect(screen.getByText("早间回顾")).toBeTruthy();
    expect((screen.getByText("＋ 新建") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("开关 早间回顾") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByText("早间回顾"));
    expect((screen.getByText("立即运行") as HTMLButtonElement).disabled).toBe(true);
  });

  it("开启后筛选、选中任务、立即运行与开关发出正确命令", async () => {
    const runNow = vi.spyOn(ipc, "runScheduleNow").mockResolvedValue();
    const toggle = vi.spyOn(ipc, "toggleScheduleJob").mockResolvedValue();
    const getRuns = vi.spyOn(ipc, "getScheduleRuns").mockResolvedValue();
    render(<SchedulerPage />);
    await feed(state(true, [job(), job({ id: "j2", name: "周报", enabled: false, schedule_text: "每周 周五 18:00" })]));
    expect(screen.queryByRole("status")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "暂停" }));
    expect(screen.queryByText("早间回顾")).toBeNull();
    expect(screen.getByText("周报")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "全部" }));

    fireEvent.click(screen.getByText("早间回顾"));
    await waitFor(() => expect(getRuns).toHaveBeenLastCalledWith("j1", 20));
    fireEvent.click(screen.getByText("立即运行"));
    expect(runNow).toHaveBeenCalledWith("j1");

    fireEvent.click(screen.getByLabelText("开关 周报"));
    expect(toggle).toHaveBeenCalledWith("j2", true);
  });

  it("运行记录：只接收当前任务的记录，安静结果与被拒工具正确展示", async () => {
    vi.spyOn(ipc, "getScheduleRuns").mockResolvedValue();
    render(<SchedulerPage />);
    await feed(state(true, [job()]));
    // 未选中：看全部记录（job_id 为空）
    await feed({ v: 1, type: "schedule.runs", job_id: "", runs: [
      run(), run({ run_id: "sch-2", quiet: true, summary: "NO_REPLY" }),
      run({ run_id: "sch-3", state: "failed", summary: "被拒", denied_tools: ["shell_run"] }),
    ] });
    expect(screen.getByText("有 2 个进行中的目标")).toBeTruthy();
    expect(screen.getByText("安静")).toBeTruthy();
    expect(screen.queryByText("NO_REPLY")).toBeNull();
    expect(screen.getByText("被拒绝的工具：shell_run")).toBeTruthy();

    // 别的任务的记录不应覆盖当前视图
    await feed({ v: 1, type: "schedule.runs", job_id: "other", runs: [run({ summary: "不该出现" })] });
    expect(screen.queryByText("不该出现")).toBeNull();
  });

  it("新建表单：每周任务组装出正确的 trigger 并保存；失败 ack 原样显示", async () => {
    const save = vi.spyOn(ipc, "saveScheduleJob").mockResolvedValue();
    render(<SchedulerPage />);
    await feed(state(true, []));
    fireEvent.click(screen.getByText("＋ 新建"));
    fireEvent.change(screen.getByLabelText("任务名称"), { target: { value: "工作日提醒" } });
    fireEvent.change(screen.getByLabelText("任务内容"), { target: { value: "提醒用户看今天的目标" } });
    fireEvent.change(screen.getByLabelText("触发方式"), { target: { value: "weekly" } });
    fireEvent.change(screen.getByLabelText("时刻"), { target: { value: "08:30" } });
    fireEvent.click(screen.getByRole("button", { name: "六" }));
    fireEvent.click(screen.getByText("创建"));
    expect(save).toHaveBeenCalledTimes(1);
    const draft = save.mock.calls[0]![0];
    expect(draft.id).toBeUndefined();
    expect(draft.trigger).toEqual({ kind: "weekly", weekdays: [0, 1, 2, 3, 4, 5], time: "08:30" });
    expect(draft.scratch).toBeNull();

    await feed({ v: 1, type: "schedule.ack", command: "schedule.save", ok: false, message: "时间格式应为 HH:MM" });
    expect(screen.getByText("时间格式应为 HH:MM")).toBeTruthy();
    expect(screen.getByText("新建任务")).toBeTruthy();          // 失败时留在表单
  });

  it("删除需要二次确认；停用事件显示原因", async () => {
    const del = vi.spyOn(ipc, "deleteScheduleJob").mockResolvedValue();
    vi.spyOn(ipc, "getScheduleRuns").mockResolvedValue();
    render(<SchedulerPage />);
    await feed(state(true, [job()]));
    fireEvent.click(screen.getByText("早间回顾"));
    fireEvent.click(screen.getByText("删除"));
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("确认删除？"));
    expect(del).toHaveBeenCalledWith("j1");

    await feed({ v: 1, type: "schedule.job_disabled",
                 job: job({ enabled: false, disabled_reason: "连续失败 5 次，已自动停用" }) });
    expect(screen.getByText("「早间回顾」已自动停用：连续失败 5 次，已自动停用")).toBeTruthy();
  });

  it("打开结果会话按钮回调专用会话 id", async () => {
    const open = vi.fn();
    render(<SchedulerPage onOpenSession={open} />);
    await feed(state(true, []));
    fireEvent.click(screen.getByText("打开结果会话"));
    expect(open).toHaveBeenCalledWith("s9");
  });
});

describe("表单辅助", () => {
  it("本地时间与 ISO 互转保持同一时刻", () => {
    const iso = localInputToIso("2026-11-28T09:00");
    expect(iso).toMatch(/^2026-11-28T09:00:00[+-]\d\d:\d\d$/);
    expect(isoToLocalInput(iso)).toBe("2026-11-28T09:00");
    expect(localInputToIso("")).toBe("");
  });

  it("清单留空为 null、工具按逗号拆分、编辑时带 id", () => {
    const d = draftFromForm({
      id: "j1", name: " 名称 ", prompt: " 内容 ", enabled: true, kind: "interval", at: "",
      everyMinutes: "30", time: "09:00", weekdays: [], expr: "", event: "app_started",
      staleDays: "3", tz: "", activeHours: "08:00-23:00", idleOnly: true,
      scratch: "   ", allowedTools: "web_search， custom_tool",
    });
    expect(d).toMatchObject({ id: "j1", name: "名称", prompt: "内容", scratch: null,
      trigger: { kind: "interval", every_s: 1800 }, allowed_tools: ["web_search", "custom_tool"],
      active_hours: "08:00-23:00" });
  });
});
