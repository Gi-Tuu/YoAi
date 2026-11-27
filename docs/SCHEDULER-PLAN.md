# Event & Scheduler 设计方案（草案 · 待拍板）

> 2026-11-27 起草。状态：**S1 / S1.1 / S2 / S3 已写完**（默认关闭，`YOAI_SCHEDULER=1` 开启）；S4 方案见 `SCHEDULER-S4-UI-PLAN.md`，S5 未做。见第 15、16 节。
> 目标：补上 README "尚未实现"第一项——让 YoAi 从"只会回答"变成"会主动做事"。

---

## 1. 现状核查（读代码确认，不是猜）

| 项 | 现状 | 结论 |
|---|---|---|
| Core 调度能力 | `yai_core` 内无 scheduler / cron / interval / checkpoint 相关实现 | 需在 YoAi 侧自建，**Core 零改动** |
| 桌面 runtime | `yoai_runtime.py`：stdin 读线程 → asyncio 主循环 → `Runtime.handle()` 分发；`start_task()` 用 `asyncio.create_task` 跑 `agent.astream()` | 调度器可作为同一事件循环里的后台协程，**复用 `start_task` 的执行链**（证据采集、流式、产物记录全部自动沿用） |
| 审批 | `_request_host("approval/request")` 发到前端并 `await` 用户点击 | **无人值守时没人点**——必须换成不弹窗的策略，否则任务永久挂起 |
| 目标 | `GoalManager`：status ∈ pending/active/done/cancelled，有 `updated_at`，**无截止时间** | "目标停滞"事件可用 `updated_at` 实现；截止时间是可选扩展 |
| 运行时生命周期 | runtime 由 Tauri 拉起，**应用关闭即退出** | v1 调度只在应用打开时运行；关闭期间错过的任务按 misfire 策略处理 |

## 2. 范围

**v1 做（三件事）**

1. **定时任务**：一次性 / 固定间隔 / 每天 / 每周。
2. **事件触发**：应用启动、目标创建或状态变化、目标 N 天未更新。
3. **长任务中断恢复**：运行日志落盘；异常退出后启动时识别"中断"的运行，可重试或手动继续。

**v1 不做（明确排除）**

- 应用关闭后仍运行（需 Windows 任务计划程序或托盘常驻进程，另起设计）。
- 完整 cron 表达式（先做四种常用类型；cron 留扩展点）。
- 文件变化监听（需要 watchdog 依赖或轮询，v2 再评估）。
- 定时任务之间的依赖编排（DAG）。

## 3. 架构

```
src/yoai/scheduler/            ← 新包，纯 Python，不依赖 Tauri/Qt，可单测
  models.py    Job / Trigger / RunRecord 数据结构
  triggers.py  next_fire_time(trigger, after, tz) 纯函数
  store.py     jobs.json 原子写 + runs.jsonl 追加 + 损坏隔离（同 goals.py 做法）
  engine.py    SchedulerEngine：tick 循环、misfire、防重叠、事件分发
  tools.py     agent 可调用的 schedule_* 工具
apps/desktop-tauri/runtime/yoai_runtime.py
  Runtime 持有 SchedulerEngine，注入 runner 回调 → 复用 start_task 执行链
```

**关键设计：引擎不认识 runtime。** `SchedulerEngine(store, runner, clock)` 只管"什么时候该跑什么"，
真正执行通过注入的 `runner(job) -> RunResult` 回调。好处：

- 单测注入假时钟 + 假 runner，毫秒级验证"跨天/错过/重叠"等时间逻辑；
- 将来做系统级后台服务时，引擎原样复用，只换 runner。

## 4. 数据模型

`data_dir/scheduler/jobs.json`

```json
{
  "a1b2c3d4": {
    "id": "a1b2c3d4",
    "name": "早间目标回顾",
    "enabled": true,
    "trigger": {"kind": "daily", "time": "09:00", "tz": "Asia/Shanghai"},
    "prompt": "列出我进行中的目标，每个给一句进度建议",
    "session": "scheduler",
    "allowed_tools": [],
    "misfire": "run_once",
    "timeout_s": 600,
    "next_fire_at": "2026-11-28T09:00:00+08:00",
    "last_run_id": "",
    "created_by": "user",
    "created_at": "...", "updated_at": "..."
  }
}
```

**触发器类型**

| kind | 参数 | 例子 |
|---|---|---|
| `once` | `at` | 2026-11-28 15:00 提醒我交作业 |
| `interval` | `every_s`（下限 300） | 每 2 小时检查一次 |
| `daily` | `time` | 每天 09:00 |
| `weekly` | `weekday` 列表 + `time` | 周一、周四 20:00 |
| `event` | `event` + 过滤条件 | `goal_stale`（`days: 3`） |

时区默认取系统本地时区（本机当前为 UTC+8）；`next_fire_at` 存带偏移的 ISO 字符串。

`data_dir/scheduler/runs.jsonl`（只追加）：`run_id / job_id / trigger_reason / started_at / finished_at /
state(running|ok|failed|timeout|interrupted|skipped) / summary / evidence_id`。

## 5. 执行语义（最容易出 bug 的地方，逐条定死）

| 问题 | 规则 |
|---|---|
| **tick 频率** | 后台协程每 30s 检查一次；精度 ±30s，对提醒类任务足够 |
| **应用关闭期间错过** | `misfire=run_once`（默认）：启动后**只补跑一次**，不按错过次数补跑；`skip`：直接算下一次 |
| **同一任务重叠** | 上一次未结束 → 本次记 `skipped`，不排队、不并发 |
| **与用户对话冲突** | 用户任务优先：用户正在跑任务时，定时任务等待（最多等 10 分钟，超时记 `skipped`）。避免两条执行链抢同一个 agent 的 `change_context` / 流式缓冲 |
| **在哪个会话里跑** | 默认专用会话「⏰ 定时任务」，**不污染用户对话历史**；可选指定已有会话 |
| **单次超时** | job 级硬上限 `timeout_s`（默认 600s）。与 `model_timeout=None` 不冲突：那是单次模型调用，这是整个任务 |
| **结果通知** | 推送 `schedule.run_finished` 到前端 + 系统通知（标题=任务名，正文=摘要前 80 字） |
| **自动禁用** | 连续失败 3 次 → `enabled=false` 并通知，防止坏任务每 30s 烧额度 |

## 6. 无人值守权限（安全核心）

现有三档（full/smart/manual）都假设"有人能点弹窗"。定时任务没有人在场，所以：

- 定时运行使用**独立的 `AllowlistPolicy`**，与会话档位无关；
- 默认白名单 = 现有 `_SMART_ALLOWED` 里的**只读 + 记忆/目标内部写**；
- 不在白名单的工具：**直接拒绝，不弹窗**（fail closed），并在运行记录里写明"被拒绝的工具：xxx"；
- 创建任务时用户可额外勾选 `allowed_tools`，但以下工具**永远不允许**无人值守：
  `shell_run`、`forget_fact`、`forget_event`、`proj_write`、`proj_patch`、所有 MCP/Skill 写类工具；
- 即使会话档位是 `full`，定时任务也不继承"全部放行"。

> 理由：一个每 30 分钟跑一次、能执行 shell 的任务，一旦 prompt 被网页内容注入，代价不可控。

## 7. 长任务中断恢复

1. 运行开始即在 `runs.jsonl` 写 `state=running`；结束时追加终态记录。
2. runtime 启动时扫描：有 `running` 而无终态的记录 → 补写 `interrupted`。
3. 处理策略（job 字段 `on_interrupt`）：`notify`（默认，只提示）/ `retry_once`（自动重跑一次）。
4. 用户对话任务同样受益：中断的对话轮在界面上显示"上次被中断，[继续]"——"继续"= 用同一输入在原会话重新发起，**不是**从中间状态恢复（Core 没有 checkpoint API，伪装断点续跑是不诚实的）。

## 8. 接口

**agent 工具**（让用户能说"每天早上九点提醒我看目标"）

| 工具 | 权限 |
|---|---|
| `schedule_list` | 进 smart 白名单（只读） |
| `schedule_create` | **不进白名单 → 弹窗确认**（会持久化自主行为） |
| `schedule_cancel` | 不进白名单 → 弹窗确认 |
| `schedule_run_now` | 不进白名单 → 弹窗确认 |

**IPC 协议 v1 追加**（同步 `docs/IPC-PROTOCOL.md`、`protocol.py`、**三份 runtime 副本**）

- 命令：`schedule.list` / `schedule.save` / `schedule.delete` / `schedule.toggle` / `schedule.run_now` / `schedule.runs`
- 消息：`schedule.state` / `schedule.run_started` / `schedule.run_finished`

**前端**：左侧导航新增「定时」页——任务列表（名称/下次运行/上次结果/开关）+ 新建表单 + 最近 20 条运行记录。

## 9. 分阶段实施

| 阶段 | 内容 | 碰现有代码？ | 验收 |
|---|---|---|---|
| **S1** | `scheduler/` 包：models/triggers/store/engine + 单测 | **不碰** | 新测试全绿，原 324 项不变 |
| S2 | runtime 接入：后台 tick、runner 复用 `start_task`、无人值守 policy、专用会话 | 改 `yoai_runtime.py` | runtime 协议测试 + 手动跑一个 1 分钟后的 once 任务 |
| S3 | agent 工具 `schedule_*` + 白名单配置 | 改 `capabilities`/`bootstrap` | 对话里"每天 9 点提醒我"能创建任务 |
| S4 | 前端「定时」页 + 系统通知 | 改 Tauri 前端 | 前端测试 + GUI 目视 |
| S5 | 事件触发（启动/目标变化/目标停滞）+ 中断恢复 | 改 runtime + goals 钩子 | 杀进程后重启能看到 interrupted |

每阶段结束需要在本机跑一次全量 pytest（AI 助手侧无法执行进程）。

## 10. 测试清单（S1 即写）

- 每天 09:00：08:59 → 当天 09:00；09:01 → 次日 09:00；跨月、跨年
- 每周：周日晚 → 下周一；多个 weekday
- interval 下限 300s；once 过期后不再触发
- misfire：关闭 3 天后启动，`run_once` 只补跑 1 次，`skip` 补跑 0 次
- 重叠：上次未完成 → `skipped`
- 连续失败 3 次自动禁用
- 无人值守 policy：白名单外工具被拒绝且不触发审批回调；黑名单工具无法被 `allowed_tools` 放行
- jobs.json 损坏 → 隔离为 `.corrupt`，不崩溃
- 中断：存在 `running` 无终态 → 启动后补写 `interrupted`

## 11. 拍板记录（2026-11-27 01:04）

1. 错过的任务：**启动后补跑一次**（`misfire=run_once` 为默认）。
2. 无人值守权限：**只读 + 记忆/目标内部写**（`scheduler/policy.py` 的 `DEFAULT_UNATTENDED`）。
3. 结果位置：**专用「⏰ 定时任务」会话**。
4. 应用关闭也运行：未拍板，v1 不做。

## 12. S1 交付状态

| 文件 | 内容 |
|---|---|
| `scheduler/models.py` | Trigger / Job / RunRecord / RunResult + 校验（中文报错） |
| `scheduler/triggers.py` | `next_fire_time` 纯函数；时区支持 本地 / UTC / `+08:00` / IANA（Windows 无 tzdata 时回退本地，不崩） |
| `scheduler/store.py` | jobs.json 原子写 + 损坏隔离；runs.jsonl 只追加，半行跳过 |
| `scheduler/policy.py` | 无人值守白名单 + 永不放行黑名单 + `UnattendedGate`（不弹窗，记账被拒工具） |
| `scheduler/engine.py` | tick / 错过补跑一次 / 防重叠 / 让路用户任务 / 超时 / 连续失败停用 / 中断补记与 retry_once / 事件（启动、目标变化、目标停滞） |
| `tests/test_scheduler.py` | 32 项，覆盖第 10 节清单 |

**验证口径（诚实标注）**：AI 助手在隔离沙箱里执行了这 32 项，全部通过（Python 3.12）。
沙箱不允许 `os.fdopen/os.fsync`，验证副本把这两处换成普通写入——**原子写路径本身未在沙箱验证**，
需本机 `pytest tests/test_scheduler.py` 确认。S1 未改动任何现有文件，原 324 项不受影响。

## 13. 对齐成熟方案（OpenClaw cron，2026-11-27 查证）

参照 OpenClaw 官方文档 `docs/automation/cron-jobs.md`：

| 维度 | OpenClaw | YoAi S1 | 结论 |
|---|---|---|---|
| 持久化 | `cron/jobs.json` + `cron/runs/<jobId>.jsonl` | `scheduler/jobs.json` + `runs.jsonl` | 一致 |
| 调度类型 | `at` / `every` / `cron` 表达式（croner，可带 IANA 时区） | once / interval / daily / weekly | **差距**：缺 cron 表达式 |
| 执行位置 | main（进主会话）或 isolated（`cron:<jobId>`，每次新会话，24h 回收） | 专用「⏰ 定时任务」会话 | 方向一致；可对齐为"每任务独立会话 + 定期回收" |
| 一次性任务 | 成功后默认删除 / 停用 | 执行后停用 | 一致 |
| 失败处理 | 指数退避重试 30s→1m→5m→15m→60m，成功后复位 | 连续 3 次失败直接停用 | **差距**：对方更宽容，建议改为"退避 + 达阈值才停用" |
| 并发 | `maxConcurrentRuns` 默认 1 | 同任务不重叠；让路用户任务 | 一致（YoAi 多一条让路规则） |
| 运行日志 | 按大小 / 行数自动裁剪 | 无裁剪 | **差距**：需补 |
| 心跳 | Heartbeat：周期性唤醒主会话，按清单检查要不要做事 | 只有"目标停滞"这一种特例 | 可把 goal_stale 泛化成 heartbeat |
| 按任务覆盖模型 / 思考档 | 支持 | 不支持 | 可选 |

**S1.1 已完成（2026-11-27）**：① cron 表达式交给 croniter（pallets-eco 维护）；
② 失败退避 30s/1m/5m/15m/60m、成功复位，连续 5 次失败才停用；③ 运行日志改为每任务一个文件，
超过 2MB 只留最新 2000 行；④ 预置默认关闭的「主动检查」（心跳）任务，支持时间窗 / 空闲才跑 / 检查清单 / NO_REPLY 安静结果。

## 14. 与 RSI 的关系（项目所有者（你）澄清，2026-11-27）

RSI 进化的本意**不是限制工具集**，而是：每次进化在树上对应节点长出新分支，
形成**足够差异化**的新节点，并登记其**能力偏好**；下次任务按能力偏好选中最合适的节点执行。
对照现有代码的差距（只读核对，未改动）：

- `evolution/candidate.py`：候选只做"补工具白名单 + 一句提示"或"补能力标签"，节点之间差异很小；
- `agent.py` 的 `tool_filter` 可以把专家 `spec.tools` 当作**工具白名单**——这正是"限制工具集"。
  **更正（补充核对）**：生产桌面路径没有接入它，只有 `bench/run_evolution_ab.py` 用了，A/B 里 D<A 来自这条路径；
- `evolution/router.py` 已经是"按能力标签打分选节点"，方向正确，但标签是静态声明，
  不是从真实成功率学到的"偏好"。

定时任务可为 RSI 提供稳定、可重复的真实样本（同一 prompt 周期运行），后续可作为能力偏好的数据来源。
完整的新设计见 `docs/RSI-TREE-V2-DESIGN.md`（待拍板，未改代码）。

## 15. S2 交付状态（2026-11-27，默认关闭）

**新增**

| 文件 | 内容 |
|---|---|
| `scheduler/host.py` | runtime 桥：专用会话（不切走用户当前会话）、独立 channel、每次运行前锁定无人值守 policy、`schedule.*` 命令、预置心跳任务只预置一次 |
| `scheduler/presets.py` | 「主动检查」（每 30 分钟、08:00–23:00、空闲才跑、默认关）与「早间目标回顾」 |
| `scheduler/__main__.py` | 命令行：`python -m yoai.scheduler list / add / enable / disable / remove / runs` |
| `tests/test_scheduler_host.py` | 10 项：会话、预置、权限锁定、审批 / 澄清不弹窗、失败判定、命令、命令行 |
| `tools/sync_runtime_copies.py` | 编译检查 + CRLF 统一 + 同步 runtime 的 4 个副本 |

**`yoai_runtime.py` 改动（11 处，全部在 `self.scheduler is not None` 之后才生效）**：
构造（读 `YOAI_SCHEDULER`）、hello 后启动、`schedule.*` 命令分发、shutdown 与进程退出时停止、
专用会话的 agent 参数注入、专用会话不跟随权限档位 / 不允许改档 / 权限说明、
用户在专用会话发消息而定时任务正在跑时拒绝。备份：`output/runtime_backup_20261127/`。

**协议 v1 追加**（前端未接，S4 做；未知类型前端会忽略）

- 命令：`schedule.list` `schedule.state` `schedule.save {job}` `schedule.delete {job_id}`
  `schedule.toggle {job_id, enabled}` `schedule.run_now {job_id}` `schedule.cancel {job_id}` `schedule.runs {job_id?, limit?}`
- 消息：`schedule.state {jobs, session_id, session_name}` `schedule.ack {command, ok, message}`
  `schedule.run_started {run}` `schedule.run_finished {run}` `schedule.run_interrupted {run}`
  `schedule.job_disabled {job}` `schedule.runs {job_id, runs}`

**验证口径**：沙箱里跑了 `test_scheduler.py` 45 项 + `test_scheduler_host.py` 10 项，全部通过；
另用假会话 / 假 agent 加载**真实的 `yoai_runtime.py`** 做了接线冒烟（未开启报错、新建、立即运行、
权限锁定、拒绝改档、并发拒绝、shutdown），通过。**没有在真机上用真实 Core 和模型跑过。**

**已知局限（S2 范围外）**

- 定时运行不走 `start_task`（那条链和界面状态耦合太深），因此**暂不采集执行证据**，RSI 还用不上这些样本；
- 所有定时任务共用一个会话，历史会越来越长；OpenClaw 的做法是每次独立上下文 + 24 小时回收，后续可对齐；
- 目标创建 / 状态变化事件还没接 GoalManager 钩子（S5）；目标停滞（每小时检查一次）和应用启动事件已可用；
- 应用关闭时不运行。

**本机验证步骤**

```bash
cd $YOAI_ROOT
PY="$CORE_PY"
export PYTHONPATH="$YOAI_ROOT/src;$YAI_CORE_SRC"
# 1. 同步 runtime 副本（2026-11-27 07:55 已同步，4 个副本与源码一致；以后改 runtime 再跑）
"$PY" tools/sync_runtime_copies.py
# 2. 测试
"$PY" -m pytest tests/test_scheduler.py tests/test_scheduler_host.py tests/test_runtime_copies.py tests/test_e2e_journey.py -q
"$PY" -m pytest -q
# 3. 只有用 cron 表达式才需要 croniter（若桌面用内置 Python，也要装到那里）
"$PY" -m pip install croniter
# 4. 实机：加一个 2 分钟后的任务，开启调度器启动 YoAi
"$PY" -m yoai.scheduler --data-dir dist/output add --name 测试 --prompt "列出我的目标" --in 2
YOAI_SCHEDULER=1 ./dist/YoAi.exe
# 2 分钟后在「⏰ 定时任务」会话里应能看到结果；查看记录：
"$PY" -m yoai.scheduler --data-dir dist/output runs
```

> 数据目录说明：优先 `YOAI_DATA_DIR`；没设时 dist 版 runtime 用 `dist/output`（目录存在的话），否则用项目根 `output/`。
> 如果结果没出现，看看这两个目录里哪个出现了 `scheduler/` 子目录，再把 `--data-dir` 指过去。

回退：把 `output/runtime_backup_20261127/source__yoai_runtime.py` 复制回 `apps/desktop-tauri/runtime/yoai_runtime.py`，再运行同步脚本。

## 16. S3 交付状态（2026-11-27 下午）：对话里管理定时任务

**对齐 OpenClaw**：OpenClaw 给智能体一个 `cron` 工具（add / list / run / remove，JSON 参数）。
YoAi 的权限白名单按工具名判断，所以拆成 6 个工具：

| 工具 | 权限 |
|---|---|
| `schedule_list` / `schedule_runs` | 只读，进 smart 白名单；无人值守也可用 |
| `schedule_create` / `schedule_cancel` / `schedule_toggle` / `schedule_run_now` | 每次弹窗确认；无人值守**永不放行**（所有非只读 `schedule_*` 进黑名单） |

有意的差异：一次性时间不带时区按**本地**理解（OpenClaw 按 UTC）；另有 `in_minutes`（"N 分钟后"），
不让模型自己算时间；星期接受 `一,三,五` / `1-5` / `工作日` / `周末`；对话创建的任务上限 20 个；
完全相同的任务不重复建（模型重试时常见）。工具说明要求 prompt 写成不依赖当前对话的完整指令。

**改动**

| 文件 | 内容 |
|---|---|
| `scheduler/tools.py`（新） | 6 个工具 + 时间 / 星期解析；工具函数同步、线程安全 |
| `scheduler/engine.py` | ① **修并发 bug**：先登记运行再 await 通知，两个同时到达的触发不会把同一任务跑两次（有回归测试，且已确认旧代码会失败）；② `request_run()` 同步入队；③ 手动 / 中断重跑不推迟原定时间 |
| `scheduler/store.py` | 任务表加 `RLock`（工具可能在工作线程里调用） |
| `scheduler/policy.py` | `schedule_runs` 只读；非只读 `schedule_*` 一律永不无人值守 |
| `scheduler/host.py` | `tool_specs()`、`notify_changed()`（任意线程可调，推一次 `schedule.state`） |
| `agent.py` | 新参数 `extra_tool_specs`（列表或 callable），坏了只打日志不影响构造 |
| `bootstrap.py` | `schedule_list` / `schedule_runs` 进 smart 白名单（两处名单都加） |
| `yoai_runtime.py` | 所有会话的 agent 带 `schedule_*`（调度器未开启时为空）；调度器改为在第一个 agent 构造**之前**创建；5 份副本已同步 |
| `tests/test_scheduler_tools.py`（新） | 12 项；`test_scheduler.py` +1 项并发回归 |

**验证口径（2026-11-27 本机）**：`test_scheduler.py` 46 项、`test_scheduler_host.py` 13 项、
`test_scheduler_tools.py` 12 项全部通过；Python 全量 **393 passed, 3 skipped**。
真模型验证：对话「20 分钟后提醒我检查项目状态」触发 `schedule_create` 审批，allow 后任务
`88da835b` 落盘；第二轮「列出定时任务」直接调用 `schedule_list`、无审批且回复正确。

**本机验收**

```bash
"$PY" -m pytest tests/test_scheduler_tools.py tests/test_scheduler.py tests/test_scheduler_host.py -q
"$PY" -m pytest -q
# 实机：YOAI_SCHEDULER=1 启动后，在普通会话里说
#   「20 分钟后提醒我喝水」→ 应弹窗确认 schedule_create → 确认后「⏰ 定时任务」会话里 20 分钟后出现结果
#   「我有哪些定时任务？」→ 不弹窗，直接列出
```

**已知局限**：工具改动后界面靠 `schedule.state` 刷新；S4 前端页已实现并通过组件测试，
但尚未做 GUI 目视。定时运行仍不采集执行证据，RSI 暂用不上这些样本。
