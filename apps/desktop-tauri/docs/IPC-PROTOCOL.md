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
