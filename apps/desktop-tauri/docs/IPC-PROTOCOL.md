# Desktop IPC 协议 v1（Tauri ↔ Python Runtime）

> 版本化、结构化、按 task_id/run_id 隔离。Python 内核语义零改动——
> runtime 只是把 `YoAiAgent.astream()` 的事件流翻译成 JSONL。

## 传输

- **通道**：Tauri 侧启动 Python 子进程，stdin 写命令、stdout 读事件，均为 **JSON Lines**（每行一个 JSON 对象，UTF-8，`\n` 结尾）。
- **stderr**：仅日志，不参与协议；runtime 必须保持 stdout 干净（只有协议行）。
- **方向**：
  - 前端 → Python：`Command`（经 Tauri Rust 桥转发）
  - Python → 前端：`Message`（经 Tauri Rust emit 到 webview）

## 通用字段

所有消息都有：

| 字段 | 类型 | 说明 |
|---|---|---|
| `v` | 1 | 协议版本，不认识则忽略并回 `error` |
| `type` | string | 消息类型 |
| `task_id` | string | 任务 ID（客户端生成，全链路携带） |
| `run_id` | string | 运行 ID（同一 task 重跑时变化） |
| `seq` | int | 同一 run 内单调递增，前端据此去重/排序 |

## 命令（前端 → Python）

### `hello`（握手，无 task）

```json
{"v":1,"type":"hello","client":"tauri","protocol":1}
```
响应 `ready`（见下）。用于启动状态与版本协商。

### `task.start`

```json
{"v":1,"type":"task.start","task_id":"t_1","run_id":"r_1","input":"记住我喜欢深色主题"}
```
启动一个任务。runtime 创建 asyncio task，`astream(input)` 逐事件推送。

### `task.cancel`

```json
{"v":1,"type":"task.cancel","task_id":"t_1","run_id":"r_1"}
```
取消指定 run。取消后发 `status(cancelled)`，后续该 run 的事件丢弃。

### `session.list` / `session.switch`

```json
{"v":1,"type":"session.list"}
{"v":1,"type":"session.switch","session_id":"s_xxx"}
```
会话管理（对应旧桌面端 SessionManager）。

### `config.get` / `config.set`

```json
{"v":1,"type":"config.get"}
{"v":1,"type":"config.set","patch":{"auto_approve":false}}
```
设置读写（对应旧设置页）。

### `shutdown`

```json
{"v":1,"type":"shutdown"}
```
优雅退出：取消所有任务、落盘、关闭 stdout。Tauri 退出时发。

## 消息（Python → 前端）

### `ready`（握手响应）

```json
{"v":1,"type":"ready","protocol":1,"python":"3.13","tools":["..."],"sessions":[...],"config":{}}
```

### `status`

```json
{"v":1,"type":"status","task_id":"t_1","run_id":"r_1","seq":0,
 "state":"queued|running|done|failed|cancelled","detail":""}
```

### `event`（Core / YoAi 事件透传）

```json
{"v":1,"type":"event","task_id":"t_1","run_id":"r_1","seq":7,
 "event":"tool_call","data":{"tool":"remember_fact","arguments":{}}}
```

`event` 取值 = Core `EventType` 全部值 + YoAi 自定义 `thinking` / `delta`。
**只使用现有可公开事件与状态，不新增/猜测模型未提供的内部推理内容**——
`thinking` 是模型真实返回的 reasoning 增量（经 provider 拦截），不是编造。

### `final`

```json
{"v":1,"type":"final","task_id":"t_1","run_id":"r_1","seq":42,"text":"最终答案..."}
```
对应 `done` 事件的 `final_text`，单独成类便于前端定稿。

### `approval.request`（用户确认）

```json
{"v":1,"type":"approval.request","task_id":"t_1","run_id":"r_1","seq":9,
 "tool":"file_create","question":"确认写入？","detail":"..."}
```
前端弹窗后回命令：
```json
{"v":1,"type":"approval.reply","task_id":"t_1","run_id":"r_1","allow":true}
```

### `error`

```json
{"v":1,"type":"error","task_id":"t_1","run_id":"r_1","seq":-1,
 "stage":"startup|runtime|protocol","message":"..."}
```

## 顺序、去重、取消规则

1. **顺序**：同一 run 内 `seq` 严格递增；跨 run 用 `(task_id, run_id)` 分组。
2. **去重**：前端按 `task_id+run_id+seq` 建 Set，重复 seq 丢弃。
3. **取消**：`task.cancel` 后该 run 不再产生新事件；已入队的事件可继续消费完（保证不半截）。
4. **重跑**：同一 task 新 run_id，前端按 run_id 分开存储，不覆盖历史。
5. **异常**：runtime 异常不静默——发 `error` + `status(failed)`；子进程退出由 Tauri 检测并提示。

## TypeScript 类型

见 `src/types/ipc.ts`（与本文件一一对应，改协议必须同步改类型与 runtime）。

## v1 扩展（2026-11-25 旧端搬迁）：会话管理 / 通讯 / 星图

旧 PySide6 端删除后，其全部能力经以下追加消息进入新端。**原有消息全部不变**，仅追加。

### 新命令（前端 → runtime）

| type | 字段 | 行为 |
|---|---|---|
| `session.state` | — | 回推一份 `snapshot` |
| `session.create` | `name` | 新建会话并切换，回推 `snapshot` |
| `session.switch` | `session_id` | 切换会话（重载历史），回推 `snapshot` |
| `session.rename` | `session_id`,`name` | 重命名，回推 `snapshot`（空名回 error） |
| `session.delete` | `session_id` | 从列表删除（历史文件保留），回推 `snapshot` |
| `chat.state` | — | 回推 `chat.state` |
| `chat.history` | `target` | 回推带 `history_target`+`history` 的 `chat.state` |
| `chat.send` | `target`,`text` | 先回 `chat.msg(own=true)`，peer 回复逐条 `chat.msg` 推送 |
| `chat.new_group` | `name` | 建群（拉入全部现有 peer），回推 `chat.state` |
| `chat.add_member` | `target`,`peer_id` | 群拉人，回推 `chat.state` |
| `chat.add_external` | `target`,`name` | 注册外部智能体并加入群，回推 `chat.state` |
| `archive.get` | — | 回推 `archive.state`（进化档案全节点） |

### 新消息（runtime → 前端）

| type | 关键字段 | 说明 |
|---|---|---|
| `snapshot` | `sessions`,`current_id`,`history`,`model`,`facts`,`goals`,`write_stats`,`tools` | 会话全景；done 后自动回推刷新侧栏 |
| `chat.state` | `conversations`(peer/group),`external`,可选 `history_target`+`history` | 通讯页全景 |
| `chat.msg` | `target`,`sender`,`name`,`content`,`own` | 单条聊天消息 |
| `archive.state` | `nodes[]`（depth 已算好） | 星图绘制数据 |

### v1 追加（右侧工具方格：浏览器 / 查看文件）

| type | 字段 | 行为 |
|---|---|---|
| `browser.open` | `url` | 仅 `http/https`；交系统浏览器作为 iframe 被拒时的兜底，成功回 `browser.opened` |
| `fs.list` | `path` | 列当前项目根（项目会话）或 `data_dir/workspace`（聊天会话）内的目录，回 `file.tree` |
| `fs.read` | `path` | 只读文本，最多 20 万字符，回 `file.content`；越界/非文件回 `error(stage=file)` |

对应新消息：`browser.opened{url}`、`file.tree{root,label,path,entries[]}`、
`file.content{root,path,content,size,truncated}`；错误阶段新增 `file`/`browser`。
终端面板不新增命令——命令作为普通 `task.start` 交给 YoAi 调 `shell_run`，审批沿用既有通道。

### v1 追加（附件 / 消息动作 / 分享）

| type | 字段 | 行为 |
|---|---|---|
| `attachment.prepare` | `path` | 复制本地文件到 `<data_dir>/attachments/<session>/`，文本类抽取进上下文，回 `attachment.ready` |
| `attachment.remove` | `id` | 发送前移除登记的附件文件 |
| `message.retract` | `index` | 撤回用户消息及其回答：写隐藏区间，回 `message.updated` + `snapshot` |
| `message.edit` | `index`,`input`,`task_id`,`run_id` | 隐藏旧分支并按新文本发新任务 |
| `task.regenerate` | `index`,`input`,`task_id`,`run_id` | 隐藏上一条助手回答并重跑 |
| `share.export` | `path`,`content`,`count` | 导出本地 `.md`/`.html`，回 `share.exported` |

新消息：`attachment.ready{attachment}`、`message.updated{kind,index,detail}`、
`share.exported{path,count}`；`snapshot.history[]` 追加 `idx`（原始历史序号）供动作定位。
错误阶段新增 `message`/`share`。撤回/编辑采用软删除+分支，原始 Core 历史不物理删除。

### v1 追加（RSI R0 用户反馈信号）

| type | 字段 | 行为 |
|---|---|---|
| `feedback.record` | `kind`,`task`,`run_id`,`note?` | 记录复制/分享/编辑/撤回/重新生成动作，绑定最近执行证据，写 `evidence/feedback.jsonl`，回 `feedback.recorded` |

`kind` 极性：负向=`retract`/`edit`/`regenerate`，正向=`copy`/`share`，中性=`continue`。
**R0 只采集，不触发进化、不写进化档案。**

### v1 追加（RSI R1 能力边界看板）

| type | 字段 | 行为 |
|---|---|---|
| `boundary.get` | — | 聚合近 30 天执行证据与 R0 反馈信号，回 `boundary.state` |

`boundary.state.report` 含总览（样本数/成功率/返工率）与按能力标签的 `rows[]`：
每行带成功率、Wilson 区间、返工率、正向信号、相对基线、状态分级。
**R1 只统计展示，不触发进化、不写进化档案。**

### v1 追加（RSI R2.1 shadow 触发）

| type | 字段 | 行为 |
|---|---|---|
| `rsi.trigger` | `tags?` | 对指定（或全部）薄弱能力边界运行触发引擎；只生成 candidate 节点，回 `rsi.triggered` 并刷新档案/看板 |

`rsi.triggered.decisions[]` 含 `tag/created/reason/node_id`。触发条件：样本 ≥20、
边界 weak、能力/路由归因 ≥60%、环境归因 <20%、7 天冷却内无同方向候选。
**候选生命周期保持 candidate，不进路由、不晋升。**

### v1 追加（RSI R2.2 隔离验证）

| type | 字段 | 行为 |
|---|---|---|
| `rsi.validate` | `node_id` | 对 candidate 节点用 held-out validation 证据跑 child/parent 成对验证，回 `rsi.validated` 并刷新档案 |

`rsi.validated.validation` 带 `verdict`、`note`、样本量、`report`（Wilson 区间）与 `promoted=false`。
**R2.2 只判定不晋升**，生命周期不变；晋升属于 R3。

### v1 追加（R3.1 受控晋升）

`rsi.validate` 完成后 runtime 自动应用晋升规则，并追加推送 `rsi.promoted`，
`decision` 含 `node_id/from_state/to_state/changed/reason/verdict`。
**只可能 candidate→probation 或 candidate→retired；probation→active 属 R3.2，需 trial + 人工批准。**

### v1 追加（R3.2 试用与批准）

| type | 字段 | 行为 |
|---|---|---|
| `rsi.trial_start` | `node_id`,`scope`,`max_n?` | 启动 tag scope 试用，返回 `trial.state`；路由临时覆盖到 probation 节点 |
| `rsi.trial_stop` | `trial_id`,`reason?` | 停止试用并清除路由覆盖 |
| `rsi.trial_report` | `trial_id` | 返回 `trial.report`（child/parent 样本、成功率、返工、成本、硬门槛） |
| `rsi.promote_active` | `trial_id`,`approved_by`,`reason?` | 人工批准后 probation→active，写 `approval.recorded` |
| `rsi.reject` | `trial_id`,`reason?` | 拒绝并 retired |

新增 `trial` 样本类别，与 evolution/validation 隔离；`ExecutionEvidence` 带 `trial_id`/`trial_role`。

### v1 追加（R3.3 parent shadow 与回滚）

| type | 字段 | 行为 |
|---|---|---|
| `rsi.rollback` | `node_id` | 手动检查 active 节点近 30 天回归，命中则 retired 并回退父节点，回 `rsi.rolled_back` |

真实任务命中 running trial 时，主证据标 `trial/child`，后台用隔离 agent 跑 parent 并落 `trial/parent`；
两侧证据带同一 `trial_id`，不推 UI 事件。active 节点每次真实任务后自动跑回归监控。

### 行为约定

1. `task` 事件序列规则不变；`snapshot` 与 run 事件流相互独立。
2. `done` 后 runtime 自动追加一份 `snapshot`（记忆/事实/目标侧栏即时刷新）。
3. final 文本由 runtime 清理 `<tool_output>` 后发出；final 为空时用本轮流式文本兜底。
4. 错误可见性：`error/permission_denied/budget_exceeded` 事件照常透传，前端在正文渲染警示并把完成态标为"部分失败"。
