/** 定时任务页（S4）：左侧任务列表、右侧详情的主从布局（参照 OpenClaw Automations 页）。
 *
 *  - 未选中：右侧显示全部任务的最近运行；
 *  - 选中任务：右侧就地编辑 + 该任务的运行记录；
 *  - 调度器未开启（未设 YOAI_SCHEDULER=1）：只读展示，所有写操作禁用。
 *  所有校验以 runtime 为准：前端只组装字段，错误原样显示 schedule.ack 的 message。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ipc } from "../lib/ipc";
import type {
  ScheduleJob, ScheduleJobDraft, ScheduleRun, ScheduleRunState, ScheduleTrigger,
  ScheduleTriggerKind,
} from "../types/ipc";

const WEEK = ["一", "二", "三", "四", "五", "六", "日"];

const KIND_LABEL: Record<ScheduleTriggerKind, string> = {
  once: "一次", interval: "固定间隔", daily: "每天", weekly: "每周", cron: "cron 表达式", event: "事件触发",
};

const STATE_LABEL: Record<ScheduleRunState, string> = {
  running: "运行中", ok: "成功", failed: "失败", timeout: "超时", interrupted: "中断", skipped: "跳过",
};

const EVENT_LABEL: Record<string, string> = {
  app_started: "应用启动时", goal_created: "新建目标时",
  goal_status_changed: "目标状态变化时", goal_stale: "目标长时间未更新时",
};

type Filter = "all" | "active" | "paused";
type Notice = { ok: boolean; text: string } | null;

// ---------------- 时间辅助 ----------------

const pad = (n: number) => String(n).padStart(2, "0");

/** datetime-local 的值（本地时间，无时区）→ 带本地偏移的 ISO。 */
export function localInputToIso(value: string): string {
  const d = new Date(value);
  if (!value || Number.isNaN(d.getTime())) return "";
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const abs = Math.abs(off);
  const base = value.length === 16 ? `${value}:00` : value.slice(0, 19);
  return `${base}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** ISO → datetime-local 的值（本地时间）。 */
export function isoToLocalInput(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmt(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}` +
    `（周${WEEK[(d.getDay() + 6) % 7]}）`;
}

function reasonLabel(reason: string): string {
  if (reason === "schedule") return "定时";
  if (reason === "misfire") return "补跑";
  if (reason === "manual") return "手动";
  if (reason === "retry_interrupted") return "中断重跑";
  if (reason.startsWith("event:")) return EVENT_LABEL[reason.slice(6)] ?? "事件";
  return reason;
}

// ---------------- 表单 ----------------

interface FormState {
  id: string;
  name: string;
  prompt: string;
  enabled: boolean;
  kind: ScheduleTriggerKind;
  at: string;            // datetime-local
  everyMinutes: string;
  time: string;
  weekdays: number[];
  expr: string;
  event: string;
  staleDays: string;
  tz: string;
  activeHours: string;
  idleOnly: boolean;
  scratch: string;
  allowedTools: string;
}

function emptyForm(): FormState {
  return {
    id: "", name: "", prompt: "", enabled: true, kind: "daily", at: "", everyMinutes: "30",
    time: "09:00", weekdays: [0, 1, 2, 3, 4], expr: "", event: "app_started", staleDays: "3",
    tz: "", activeHours: "", idleOnly: true, scratch: "", allowedTools: "",
  };
}

function formFromJob(job: ScheduleJob): FormState {
  const t = job.trigger;
  return {
    id: job.id, name: job.name, prompt: job.prompt, enabled: job.enabled, kind: t.kind,
    at: isoToLocalInput(t.at), everyMinutes: String(Math.round((t.every_s ?? 1800) / 60)),
    time: t.time || "09:00", weekdays: t.weekdays ?? [], expr: t.expr ?? "",
    event: t.event || "app_started", staleDays: String((t.params?.days as number | undefined) ?? 3),
    tz: t.tz ?? "", activeHours: job.active_hours, idleOnly: job.idle_only,
    scratch: job.scratch ?? "", allowedTools: job.allowed_tools.join(", "),
  };
}

export function draftFromForm(f: FormState): ScheduleJobDraft {
  let trigger: ScheduleTrigger;
  switch (f.kind) {
    case "once": trigger = { kind: "once", at: localInputToIso(f.at) }; break;
    case "interval": trigger = { kind: "interval", every_s: Math.round(Number(f.everyMinutes) * 60) }; break;
    case "daily": trigger = { kind: "daily", time: f.time }; break;
    case "weekly": trigger = { kind: "weekly", weekdays: [...f.weekdays].sort(), time: f.time }; break;
    case "cron": trigger = { kind: "cron", expr: f.expr.trim() }; break;
    default:
      trigger = { kind: "event", event: f.event,
                  params: f.event === "goal_stale" ? { days: Number(f.staleDays) } : {} };
  }
  if (f.tz.trim()) trigger.tz = f.tz.trim();
  const draft: ScheduleJobDraft = {
    name: f.name.trim(), prompt: f.prompt.trim(), enabled: f.enabled, trigger,
    active_hours: f.activeHours.trim(), idle_only: f.idleOnly,
    // 清单留空 = 没有清单（照常运行）；有内容才作为检查清单附在任务后面
    scratch: f.scratch.trim() ? f.scratch : null,
    allowed_tools: f.allowedTools.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean),
  };
  if (f.id) draft.id = f.id;
  return draft;
}

function JobForm({ initial, readOnly, onSave, onCancel }: {
  initial: FormState; readOnly: boolean;
  onSave: (draft: ScheduleJobDraft) => void; onCancel: () => void;
}) {
  const [f, setF] = useState<FormState>(initial);
  useEffect(() => setF(initial), [initial]);
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setF((prev) => ({ ...prev, [key]: value }));
  const toggleDay = (d: number) =>
    set("weekdays", f.weekdays.includes(d) ? f.weekdays.filter((x) => x !== d) : [...f.weekdays, d]);

  return (
    <form className="sched-form" onSubmit={(e) => { e.preventDefault(); if (!readOnly) onSave(draftFromForm(f)); }}>
      <fieldset disabled={readOnly}>
        <label>名称
          <input aria-label="任务名称" value={f.name} onChange={(e) => set("name", e.target.value)} />
        </label>
        <label>任务内容
          <textarea aria-label="任务内容" rows={4} value={f.prompt}
                    placeholder="写成不依赖当前对话的完整指令，例如：列出我进行中的目标，每个给一句今天的建议。"
                    onChange={(e) => set("prompt", e.target.value)} />
        </label>

        <div className="sched-row">
          <label>触发方式
            <select aria-label="触发方式" value={f.kind}
                    onChange={(e) => set("kind", e.target.value as ScheduleTriggerKind)}>
              {(Object.keys(KIND_LABEL) as ScheduleTriggerKind[]).map((k) => (
                <option key={k} value={k}>{KIND_LABEL[k]}</option>
              ))}
            </select>
          </label>
          {f.kind === "once" && (
            <label>时间
              <input aria-label="运行时间" type="datetime-local" value={f.at}
                     onChange={(e) => set("at", e.target.value)} />
            </label>
          )}
          {f.kind === "interval" && (
            <label>每隔（分钟，至少 5）
              <input aria-label="间隔分钟" type="number" min={5} value={f.everyMinutes}
                     onChange={(e) => set("everyMinutes", e.target.value)} />
            </label>
          )}
          {(f.kind === "daily" || f.kind === "weekly") && (
            <label>时刻
              <input aria-label="时刻" type="time" value={f.time} onChange={(e) => set("time", e.target.value)} />
            </label>
          )}
          {f.kind === "cron" && (
            <label>表达式
              <input aria-label="cron 表达式" value={f.expr} placeholder="30 9 * * 1-5"
                     onChange={(e) => set("expr", e.target.value)} />
            </label>
          )}
          {f.kind === "event" && (
            <label>事件
              <select aria-label="事件" value={f.event} onChange={(e) => set("event", e.target.value)}>
                {Object.entries(EVENT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
          )}
          {f.kind === "event" && f.event === "goal_stale" && (
            <label>天数
              <input aria-label="停滞天数" type="number" min={1} value={f.staleDays}
                     onChange={(e) => set("staleDays", e.target.value)} />
            </label>
          )}
        </div>

        {f.kind === "weekly" && (
          <div className="sched-week" role="group" aria-label="星期">
            {WEEK.map((w, i) => (
              <button key={w} type="button" aria-pressed={f.weekdays.includes(i)}
                      className={f.weekdays.includes(i) ? "on" : ""} onClick={() => toggleDay(i)}>
                {w}
              </button>
            ))}
          </div>
        )}
        {f.kind === "cron" && <p className="sched-hint">cron 表达式由后端的 croniter 解析，需要先安装 croniter。</p>}

        <details className="sched-advanced">
          <summary>高级设置</summary>
          <div className="sched-row">
            <label>执行时间窗
              <input aria-label="执行时间窗" value={f.activeHours} placeholder="08:00-23:00（留空不限）"
                     onChange={(e) => set("activeHours", e.target.value)} />
            </label>
            <label>时区
              <input aria-label="时区" value={f.tz} placeholder="留空 = 本机时区"
                     onChange={(e) => set("tz", e.target.value)} />
            </label>
          </div>
          <label className="sched-check">
            <input type="checkbox" checked={f.idleOnly} onChange={(e) => set("idleOnly", e.target.checked)} />
            只在我没有对话时运行
          </label>
          <label>检查清单（可选）
            <textarea aria-label="检查清单" rows={3} value={f.scratch} placeholder="- 进行中的目标里有没有 3 天没进展的？"
                      onChange={(e) => set("scratch", e.target.value)} />
          </label>
          <label>额外放行的工具（逗号分隔）
            <input aria-label="额外放行工具" value={f.allowedTools} onChange={(e) => set("allowedTools", e.target.value)} />
          </label>
          <p className="sched-hint">
            定时运行时没人在场，默认只能用只读和记忆类工具。这里可以额外放行，但执行命令、写文件、删除记忆、
            MCP / 技能写操作、管理定时任务这些工具始终不会放行。
          </p>
        </details>

        <label className="sched-check">
          <input type="checkbox" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          开启
        </label>
      </fieldset>
      <div className="sched-actions">
        <button type="submit" disabled={readOnly}>{f.id ? "保存" : "创建"}</button>
        <button type="button" onClick={onCancel}>{f.id ? "关闭" : "取消"}</button>
      </div>
    </form>
  );
}

// ---------------- 运行记录 ----------------

function RunList({ runs, showJob }: { runs: ScheduleRun[]; showJob: boolean }) {
  if (runs.length === 0) return <div className="side-empty">还没有运行记录。</div>;
  return (
    <ul className="sched-runs">
      {runs.map((r) => (
        <li key={`${r.run_id}-${r.state}`}>
          <div className="sched-run-head">
            <span className={`sched-state st-${r.state}`}>{r.quiet && r.state === "ok" ? "安静" : STATE_LABEL[r.state]}</span>
            {showJob && <b>{r.job_name || r.job_id}</b>}
            <span className="sched-dim">{fmt(r.started_at)} · {reasonLabel(r.reason)}</span>
          </div>
          {r.summary && !r.quiet && <div className="sched-summary">{r.summary}</div>}
          {r.denied_tools.length > 0 && (
            <div className="sched-denied">被拒绝的工具：{r.denied_tools.join("、")}</div>
          )}
        </li>
      ))}
    </ul>
  );
}

// ---------------- 页面 ----------------

export function SchedulerPage({ onOpenSession }: { onOpenSession?: (sessionId: string) => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [session, setSession] = useState({ id: "", name: "⏰ 定时任务" });
  const [selected, setSelected] = useState<string | null>(null);   // job id / "new" / null
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [notice, setNotice] = useState<Notice>(null);
  const [confirmDelete, setConfirmDelete] = useState("");

  const runsKey = useRef("");            // 当前右侧在看哪个任务的记录（"" = 全部）
  const pendingCreate = useRef(false);

  const loadRuns = useCallback((jobId: string) => {
    runsKey.current = jobId;
    void ipc.getScheduleRuns(jobId, 20);
  }, []);

  useEffect(() => {
    const off = ipc.onMessage((m) => {
      if (m.type === "schedule.state") {
        setEnabled(m.enabled);
        setJobs(m.jobs);
        setSession({ id: m.session_id, name: m.session_name || "⏰ 定时任务" });
      } else if (m.type === "schedule.runs") {
        if ((m.job_id || "") === runsKey.current) setRuns(m.runs);
      } else if (m.type === "schedule.ack") {
        setNotice({ ok: m.ok, text: m.message });
        if (m.ok && m.command === "schedule.save" && pendingCreate.current) setSelected(null);
        if (m.ok && m.command === "schedule.delete") setSelected(null);
        pendingCreate.current = false;
      } else if (m.type === "schedule.run_finished" || m.type === "schedule.run_interrupted") {
        if (runsKey.current === "" || runsKey.current === m.run.job_id) loadRuns(runsKey.current);
        if (m.run.state === "failed" || m.run.state === "timeout") {
          setNotice({ ok: false, text: `「${m.run.job_name}」${STATE_LABEL[m.run.state]}：${m.run.summary.slice(0, 80)}` });
        }
      } else if (m.type === "schedule.run_started") {
        if (runsKey.current === "" || runsKey.current === m.run.job_id) loadRuns(runsKey.current);
      } else if (m.type === "schedule.job_disabled") {
        setNotice({ ok: false, text: `「${m.job.name}」已自动停用：${m.job.disabled_reason}` });
      }
    });
    void ipc.getScheduleState();
    return off;
  }, [loadRuns]);

  // 选中变化时切换右侧的运行记录
  useEffect(() => {
    if (selected === "new") return;
    loadRuns(selected ?? "");
  }, [selected, loadRuns]);

  const readOnly = enabled !== true;
  const visible = useMemo(() => jobs.filter((j) => {
    if (filter === "active" && !j.enabled) return false;
    if (filter === "paused" && j.enabled) return false;
    const q = query.trim();
    return !q || j.name.includes(q) || j.prompt.includes(q);
  }), [jobs, filter, query]);
  const current = selected && selected !== "new" ? jobs.find((j) => j.id === selected) ?? null : null;
  const formInitial = useMemo(() => (current ? formFromJob(current) : emptyForm()),
    // 只在换任务时重置表单；同一任务的状态刷新不覆盖正在编辑的内容
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [current?.id, selected]);

  const save = (draft: ScheduleJobDraft) => {
    pendingCreate.current = !draft.id;
    setNotice(null);
    void ipc.saveScheduleJob(draft);
  };

  return (
    <div className="sched-page">
      <header className="boundary-head">
        <div>
          <h2>定时任务</h2>
          <p>到点自动执行 · 结果放在「{session.name}」会话 · 定时运行时只能用只读和记忆类工具</p>
        </div>
        <div className="sched-head-actions">
          {session.id && onOpenSession && (
            <button type="button" onClick={() => onOpenSession(session.id)}>打开结果会话</button>
          )}
          <button type="button" onClick={() => void ipc.getScheduleState()}>↻ 刷新</button>
          <button type="button" disabled={readOnly} onClick={() => setSelected("new")}>＋ 新建</button>
        </div>
      </header>

      {enabled === false && (
        <div className="sched-banner" role="status">
          定时任务未开启：设置环境变量 <code>YOAI_SCHEDULER=1</code> 后重启 YoAi。现在只能查看，不能修改。
        </div>
      )}
      {notice && <div className={`boundary-notice ${notice.ok ? "" : "sched-notice-bad"}`}>{notice.text}</div>}

      <div className="sched-layout">
        <section className="sched-list">
          <div className="sched-filters" role="tablist">
            {(["all", "active", "paused"] as Filter[]).map((k) => (
              <button key={k} type="button" role="tab" aria-selected={filter === k}
                      className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
                {{ all: "全部", active: "开启", paused: "暂停" }[k]}
              </button>
            ))}
            <input aria-label="搜索任务" placeholder="搜索" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          {visible.length === 0 && (
            <div className="side-empty">
              {jobs.length === 0 ? "还没有定时任务。也可以直接在对话里说「每天 9 点提醒我看目标」。" : "没有符合条件的任务。"}
            </div>
          )}
          {visible.map((j) => (
            <div key={j.id} className={`sched-item ${selected === j.id ? "sel" : ""} ${j.enabled ? "" : "off"}`}>
              <button type="button" className="sched-item-main" onClick={() => setSelected(j.id)}>
                <span className="sched-item-name">{j.name}</span>
                <span className="sched-dim">{j.schedule_text}</span>
                <span className="sched-dim">
                  {j.running ? "运行中…" : j.waiting ? "等待空闲" : j.enabled ? `下次 ${fmt(j.next_fire_at)}` : (j.disabled_reason || "已暂停")}
                </span>
              </button>
              <div className="sched-item-side">
                {j.last_state && <span className={`sched-state st-${j.last_state}`}>{STATE_LABEL[j.last_state]}</span>}
                <label className="sched-switch" title={j.enabled ? "暂停" : "开启"}>
                  <input type="checkbox" aria-label={`开关 ${j.name}`} checked={j.enabled} disabled={readOnly}
                         onChange={(e) => void ipc.toggleScheduleJob(j.id, e.target.checked)} />
                </label>
              </div>
            </div>
          ))}
        </section>

        <section className="sched-detail">
          {selected === "new" && (
            <>
              <h3>新建任务</h3>
              <JobForm initial={formInitial} readOnly={readOnly} onSave={save} onCancel={() => setSelected(null)} />
            </>
          )}
          {current && (
            <>
              <div className="sched-detail-head">
                <h3>{current.name}</h3>
                <div className="sched-actions">
                  {current.running ? (
                    <button type="button" disabled={readOnly} onClick={() => void ipc.cancelScheduleRun(current.id)}>停止运行</button>
                  ) : (
                    <button type="button" disabled={readOnly} onClick={() => void ipc.runScheduleNow(current.id)}>立即运行</button>
                  )}
                  {confirmDelete === current.id ? (
                    <button type="button" className="sched-danger" disabled={readOnly}
                            onClick={() => { setConfirmDelete(""); void ipc.deleteScheduleJob(current.id); }}>
                      确认删除？
                    </button>
                  ) : (
                    <button type="button" disabled={readOnly} onClick={() => setConfirmDelete(current.id)}>删除</button>
                  )}
                </div>
              </div>
              {current.disabled_reason && <div className="sched-denied">{current.disabled_reason}</div>}
              <JobForm initial={formInitial} readOnly={readOnly} onSave={save} onCancel={() => setSelected(null)} />
              <h3>运行记录</h3>
              <RunList runs={runs} showJob={false} />
            </>
          )}
          {selected === null && (
            <>
              <h3>最近运行</h3>
              <RunList runs={runs} showJob />
            </>
          )}
          {selected && selected !== "new" && !current && (
            <div className="side-empty">这个任务已经不存在了。</div>
          )}
        </section>
      </div>
    </div>
  );
}
