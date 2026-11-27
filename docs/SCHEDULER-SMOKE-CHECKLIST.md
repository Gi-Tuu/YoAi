# 定时任务实机 smoke 清单（2026-11-27）

> 验证目标：S1/S1.1/S2 在**真实 Core + 真实模型**下能触发、执行、回传结果。
> 2026-11-27 19:56 起定时任务默认开启；下文 `YOAI_SCHEDULER=1` 是显式写法，等价于默认。
> 默认开启但预置任务全关，验证完请删除/停用测试任务，正常桌面路径不受影响。

## 1. 已完成的 headless smoke（2026-11-27 13:51–13:52）

用临时数据目录 `<临时数据目录>`、真实 `dist/runtime/yoai_runtime.py`、
真实 Core venv 与生产网关执行：

```bash
export YOAI_DATA_DIR=<临时数据目录>
export YOAI_SCHEDULER=1
python -m yoai.scheduler --data-dir "$YOAI_DATA_DIR" add \
  --name 冒烟 --prompt "用 list_goals 查看并一句话说明当前有没有进行中的目标；如果没有就回复：没有进行中的目标。" --in 1
./dist/YoAi.exe
python -m yoai.scheduler --data-dir "$YOAI_DATA_DIR" runs
```

结果：

| 项 | 结果 |
|---|---|
| `hello` / `schedule.state` | 正常，看到「冒烟」任务与「⏰ 定时任务」专用会话 |
| `schedule.run_started` | `run_id=sch-f0babebc`，`state=running` |
| `schedule.run_finished` | `state=ok`，摘要「没有进行中的目标。」 |
| 耗时 | 约 7 秒（13:52:06 → 13:52:13） |
| `denied_tools` | 空；`list_goals` 在无人值守白名单内 |
| 审批弹窗 | 无（headless 通道 fail-closed） |
| runtime 退出 | `shutdown` 后 exit 0 |

结论：**真实模型执行链已打通**，不再是只靠假 runner 的单测。

## 2. 可重复的 GUI 目视清单

如果要连桌面 UI 一起看，按同样步骤启动，然后逐项确认：

1. 启动前
   - [ ] 任务已加到 `YOAI_DATA_DIR` 指向的数据目录；
   - [ ] 当前会话不是「⏰ 定时任务」，启动后也没有被切走。

2. 到点前后
   - [ ] 收到 `schedule.run_started` 时界面不报错；
   - [ ] 到点后 1–2 分钟内收到 `schedule.run_finished`；
   - [ ] 结果只出现在「⏰ 定时任务」会话，不污染当前对话。

3. 权限
   - [ ] 全程没有审批弹窗；
   - [ ] 在专用会话试图改权限档位会被拒绝；
   - [ ] 若 prompt 里要求 `shell_run`，运行记录 `denied_tools` 应出现它，且状态 fail-closed。

4. 收尾
   - [ ] `python -m yoai.scheduler --data-dir "$YOAI_DATA_DIR" runs` 能看到 `ok` 记录；
   - [ ] 删除或停用测试任务；
   - [ ] 关闭 YoAi，确认 runtime 正常退出，没有残留进程。

## 3. 失败时怎么定位

| 现象 | 先查什么 |
|---|---|
| 没有 `schedule.state` | 是否设了 `YOAI_SCHEDULER=0` 导致关闭；runtime 日志里 `scheduler init failed` |
| 任务不触发 | 数据目录是否和 CLI 一致；`next_fire_at` 是否已过；`active_hours` 是否在窗口外 |
| 触发但没结果 | `runs` 里的 `state` / `summary`；网关错误；是否没有收到 `done` 事件 |
| `state=failed` 且 `denied_tools` 非空 | prompt 用了白名单外工具；这是安全设计，不是 bug |
| 反复失败后任务停用 | 连续失败 5 次自动停用，先看 `disabled_reason` 再修 prompt |

## 4. 注意

- 一次性任务执行后会自动停用，不会重复跑。
- 心跳预置任务默认关闭；删掉后不会再自动出现。
- cron 表达式需要额外安装 `croniter`；once/interval/daily/weekly 不需要。
- 本清单只验证「应用打开时」的调度；应用关闭后不运行是 v1 明确范围外。

## 5. S3 对话工具真模型验证（2026-11-27 15:44）

用临时数据目录 + `YOAI_SCHEDULER=1` + 真实 `dist/runtime`，连续发两轮对话：

1. 「请在 20 分钟后提醒我检查项目状态。提示词请写完整……」
   - 收到 `approval.request`，工具=`schedule_create`，参数 `in_minutes=20`；
   - 自动 reply `allow=true` 后收到 `tool_call` / `tool_result`（`ok=true`）；
   - 任务落盘：id `88da835b`，名称「检查项目状态提醒」，一次性，16:04 触发；
   - 最终回复明确给出任务名、id、时间与完整 prompt。
2. 「列出我现在所有的定时任务，告诉我任务名和下次运行时间。」
   - 模型调用 `schedule_list`；**没有审批弹窗**（只读工具进 smart 白名单）；
   - 最终回复正确列出「主动检查」（暂停）与「检查项目状态提醒」（16:04）。

结论：S3 的创建与列出链路在真模型下可用；写工具弹窗、读工具免弹窗的边界符合设计。
该验证只创建任务，没有等待 20 分钟触发；定时执行链路由第 1 节 smoke 覆盖。

## 6. S5 新上下文真模型对照（2026-11-27 19:10）

同一专用会话里放两个任务：`marker` 只输出 `YOAI-FRESH-MARKER-7788`；
`checker` 只看当前对话上下文，不调用记忆工具，回答是否看到上一轮助手回复里的大写英文+数字标记。
用 `schedule.run_now` 依次触发，分别做两组：

| 配置 | marker 输出 | checker 输出 | 结论 |
|---|---|---|---|
| `YOAI_SCHEDULER_FRESH=1`（默认） | `YOAI-FRESH-MARKER-7788` | **没看到标记** | 新上下文生效，第二次运行看不到第一次 |
| `YOAI_SCHEDULER_FRESH=0`（对照） | `YOAI-FRESH-MARKER-7788` | **看到标记** | 关闭窗口后能看到历史，证明差异来自 `RunWindowMemory` |

结论：S5 的「每次运行用新上下文」在真实模型下按开关正确工作；个人事实/目标/事件记忆仍跨运行共享，
不在本验证范围内。
