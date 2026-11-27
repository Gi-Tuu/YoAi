# S4 前端「定时」页方案（2026-11-27）

> YoAi 侧扩展，Core 零改动。状态：**代码已写（2026-11-27 下午）**，前端测试 / typecheck / build 已在本机通过，GUI 目视待做，见文末第 8 节。
> 前置：S1/S1.1/S2 已在 master；定时任务默认开启，开箱即食；`YOAI_SCHEDULER=0` 可显式关闭。

## 1. 目标

让定时任务从「CLI 可用」变成「产品里可用」：

- 看见任务列表、下次运行时间、上次结果、开关状态；
- 新建 / 编辑 / 删除 / 立即运行 / 取消运行 / 查看运行记录；
- 调度器未开启时明确提示，不静默失败；
- 运行开始 / 完成 / 失败 / 停用能在界面看到。

本阶段不做：对话里的 `schedule_*` 工具（S3）、GoalManager 钩子与完整恢复（S5）、
系统级常驻进程（应用关闭后仍运行）。

## 2. 现有协议（S2 已定义，直接复用）

命令：

```
schedule.list / schedule.state
schedule.save {job}
schedule.delete {job_id}
schedule.toggle {job_id, enabled}
schedule.run_now {job_id}
schedule.cancel {job_id}
schedule.runs {job_id?, limit?}
```

消息：

```
schedule.state      {jobs, session_id, session_name}
schedule.ack        {command, ok, message}
schedule.run_started    {run}
schedule.run_finished   {run}
schedule.run_interrupted {run}
schedule.job_disabled   {job}
schedule.runs       {job_id, runs}
```

**S4 需要的唯一后端小改动**：`schedule.state` 增加 `enabled: bool`，值为
`self.scheduler is not None`。前端据此显示「未开启」横幅；不需要新增 IPC 命令。

## 3. 页面结构

左侧导航新增「定时」，路由与权限一样走既有壳层。页面四块：

1. **顶部状态条**
   - 调度器状态：`开启 / 未开启`；
   - 被显式关闭时显示：`移除 YOAI_SCHEDULER=0 后重启 YoAi`；
   - 专用会话名：`⏰ 定时任务`，给出「打开会话」按钮（切到该 session）。
   - 未开启时只读展示任务，不允许「立即运行 / 取消 / 新建」；编辑保存可允许，
     因为 CLI 也允许在关闭时管理任务。

2. **任务列表**
   - 每行：名称、触发描述（`schedule_text`）、下次运行、上次状态、开关；
   - 操作：编辑、立即运行、运行中取消、删除、查看运行记录；
   - 连续失败停用 / 一次性任务已执行：显示 `disabled_reason`；
   - 运行中 / 等待前台空闲：显示状态 chip。

3. **新建 / 编辑表单**
   - 基础：名称、任务内容（prompt）、是否启用；
   - 触发类型：`once` / `interval` / `daily` / `weekly` / `cron` / `event`；
   - 参数：
     - once：本地时间；
     - interval：分钟（后端下限 5 分钟）；
     - daily：HH:MM；
     - weekly：星期多选 + HH:MM；
     - cron：表达式（明确提示需要 croniter）；
     - event：事件名 + 参数（goal_stale 天数）。
   - 高级：时区、执行时间窗 `active_hours`、仅空闲运行 `idle_only`、
     检查清单 `scratch`、清单为空即跳过、额外放行工具 `allowed_tools`。
   - **安全文案**：额外放行工具不能绕过黑名单；`shell_run`、文件写入、删除记忆、
     MCP/Skill 写工具、`ct_anchor` 永不放行。

4. **运行记录**
   - 最近 20 条，按时间倒序；
   - 列：开始时间、任务名、状态、触发原因、摘要、被拒工具；
   - `NO_REPLY` / `HEARTBEAT_OK` 显示「安静」；
   - 可按任务过滤。

## 4. 前端文件

| 文件 | 改动 |
|---|---|
| `src/types/ipc.ts` | 新增 `ScheduleStateMsg / ScheduleAckMsg / ScheduleRunMsg / ScheduleRunsMsg`；Command union 追加 `schedule.*`；`RuntimeMsg` union 追加对应消息 |
| `src/lib/ipc.ts` | 新增 `getScheduleState / saveScheduleJob / deleteScheduleJob / toggleScheduleJob / runScheduleNow / cancelScheduleRun / getScheduleRuns` |
| `src/components/SchedulerPage.tsx` | 新页面，四块结构如上 |
| `src/App.tsx` | 左侧导航加「定时」项 |
| 样式 | 复用 `mcp-page` / `boundary-*` 现有类，不另起设计系统 |
| `tests/scheduler-page.test.tsx` | 协议消息驱动 UI 状态回归（见第 6 节） |

## 5. 交互细节

- `schedule.save` 新建时 id 留空；编辑时带原 id 与 `created_at` 等字段，runtime 只合并
  `EDITABLE_FIELDS`，不会覆盖运行统计。
- `schedule.toggle` 开启前若任务时间已过，后端会报「设定的时间已经过去了」；
  前端把 ack 的 `message` 原样显示，并留在编辑态让用户改时间。
- `schedule.run_now` 返回 ack 后不一定马上有结果：若前台有任务，runtime 会排队；
  页面应等 `schedule.run_started`，不要显示「已完成」。
- 专用会话的权限固定为无人值守白名单，前端在切换过去时沿用 runtime 推来的
  `permission.state` 描述，不再提供改档控件。
- 系统通知：本阶段先做应用内提示条；若要接 Tauri notification 插件，另起小项，
  避免为了一个提示改打包依赖。

## 6. 验收

- 前端：`npm test` 新增 `scheduler-page.test.tsx`，至少覆盖
  - `schedule.state` 驱动列表与「未开启」横幅；
  - `schedule.run_finished` 更新上次状态；
  - `schedule.job_disabled` 显示停用原因；
  - 点击立即运行 / 删除发出正确命令。
- 类型：`npm run typecheck`、`npm run build` 通过。
- 真机：默认启动，页面能看到冒烟任务；立即运行一次并在列表看到结果。
- 不变式：`YOAI_SCHEDULER=0` 显式关闭时页面只读；默认开启但预置任务全关，不会自动跑任务。

## 7. 明确不做

- 不在前端保存任何 key / 凭据；
- 不绕过无人值守白名单；
- 不做 cron 表达式本地解析（完全交后端 croniter）；
- 不做任务 DAG 依赖编排；
- 不做应用关闭后常驻运行。

## 8. 实现记录（2026-11-27）

**对齐 OpenClaw**：其 Control UI 的 Automations 页改为主从布局——左侧任务列表（全部 / 开启 / 暂停 + 搜索），
右侧就地编辑选中任务并显示该任务的运行记录；未选中时显示全部任务的最近运行。S4 按同样结构实现。

| 文件 | 内容 |
|---|---|
| `src/components/SchedulerPage.tsx`（新） | 主从布局；表单覆盖 6 种触发方式 + 高级设置；删除二次确认；未开启只读 |
| `src/types/ipc.ts` | `ScheduleJob / ScheduleRun / ScheduleTrigger / ScheduleJobDraft` + 5 种消息 + 7 个命令 |
| `src/lib/ipc.ts` | `getScheduleState / saveScheduleJob / deleteScheduleJob / toggleScheduleJob / runScheduleNow / cancelScheduleRun / getScheduleRuns` |
| `src/App.tsx` | 左侧导航「定时」；「打开结果会话」切到专用会话 |
| `src/styles/app.css` | `.sched-*`，零圆角 / 1px 描边 / 无阴影，沿用纸墨令牌 |
| `tests/scheduler-page.test.tsx`（新） | 8 项：未开启横幅、筛选与命令、运行记录过滤与安静结果、新建组装 trigger、失败 ack、二次确认删除、停用提示、时间互转 |
| 后端 | `schedule.state` 加 `enabled`；未开启时 `disabled_message()` 只读回答；新建只接受可编辑字段、带未知 id 报错 |

与第 2 节的差异：未开启时**编辑也禁用**（runtime 未开启时无法保存，与其让用户填完再报错，不如直接只读）。

**验证口径（2026-11-27 本机）**：Python 侧 `test_scheduler_host.py` 13 项通过；
`npm run typecheck && npm test && npm run build` 全绿，前端 **36 passed**（新增 8 项 scheduler-page 测试）。
协议 smoke 另验证调度器 ON/OFF 分别返回 `enabled=true/false`。GUI 目视仍待做。
