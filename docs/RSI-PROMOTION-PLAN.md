# R3 晋升方案（2026-11-26，待实现）

> 目标：把 RSI 从「能提出候选、能隔离验证」推进到「受控晋升 + 可回滚」。
> 核心口径：**improved 只进 probation，不直接进 active**。
> 归属：YoAi 侧状态机与 runtime 命令，Core 零改动。

## 一、状态机总览

```
candidate ──isolation improved──> probation ──trial pass + approve──> active
   │                                  │                                │
   ├─ no_regression / insufficient ───┤                                │
   │    留在 candidate，继续采样        │                                │
   │                                  │                                │
   └────────── regression ────────────┴───────────────────────────────> retired

retired 为终态；恢复/重试走新 candidate 节点，不复活旧节点。
父节点产生子节点后不自动退役，仍可作为路由回退点。
```

## 二、candidate → probation：自动，但只进状态

触发条件（全部满足）：

1. R2.2 隔离验证结论为 `improved`；
2. child/parent 每个相关能力边界的 validation 样本各 **≥5**（R2.2 当前 smoke 8 条满足）；
3. 没有任一边界的置信下界低于父节点（不允许「一处提升、另一处退化」）；
4. 候选 diff 是**单维度**（tools / prompt / capability_tags 三选一）；
5. 成本守卫：平均 token 不超过父节点 **+20%**；
6. 7 天冷却无同方向候选。

通过后：
- `candidate → probation`；
- 写 `rsi_promotion` 报告：`from=candidate, to=probation, gate=isolation_validation`；
- **不进生产路由**（probation 默认不参与 `routing_candidates()`）。

不满足时：
- `no_regression`：留 candidate，写报告，不反复触发；
- `insufficient`：留 candidate，等更多 validation 样本；
- `regression`：`candidate → retired`，写拒绝原因，保留血统。

## 三、probation → active：试用门槛与批准流程（定版 v1）

Probation 默认**不参与正常路由**。获得真实试用数据必须显式开启 trial。
本节是可直接实现的口径；trial 阶段只做安全确认，不再要求「显著优于父节点」——
增益已在 R2.2 隔离验证中证明，trial 负责证明「真实使用中没退化」。

### 3.1 Trial 单元

- `trial_id`：唯一；绑定 `node_id`、`parent_id`、主能力标签 `primary_tag`。
- `scope`：二选一
  - `session:<session_id>`：指定会话内试用；
  - `tag:<capability_tag>`：命中该能力标签的任务试用。
- `max_n`：默认 30，允许 20–50；达到上限自动停止收集。
- `expires_at`：默认 7 天；到期停止 trial，但**不自动退役**，保持 probation。
- 同一节点同时最多一个 running trial；同一 scope 同时最多一个 trial。
- 成对采样：每条试用任务正常输出由 child 产生；同时在后台用相同任务跑 parent，
  只落证据、不展示给用户，保证 child/parent 同题可比。

### 3.2 样本隔离

- 新增样本类别 `SAMPLE_TRIAL = "trial"`，加入 `SAMPLE_CLASSES`。
- `ExecutionEvidence` 增加 `trial_id` 与 `trial_role`（`child` / `parent`）字段。
- trial 证据：
  - 不进 `validation_set()`，不参与 candidate→probation 的 BenchmarkLab 验证；
  - 不进 R1 边界看板的正/负样本，避免把试用任务当自然使用反馈；
  - 只进 trial report 与审计日志。

### 3.3 试用硬门槛（全部满足才允许申请批准）

设 `primary_tag = node.diff.tag`。

1. **样本量**：child 与 parent 在 primary_tag 上各 ≥20 条 trial 证据。
2. **成功率**：
   - `child_rate >= parent_rate - 0.02`（允许 2pp 噪声）；
   - `child_ci_low >= parent_ci_low - 0.05`（置信下界不得比父节点低 5pp 以上）。
3. **能力边界**：任何 child 样本 ≥5 的边界，不得出现
   `child_ci_low < parent_ci_low - 0.05`。
4. **返工率**：`child_rework <= parent_rework + 0.05` 且 `child_rework <= 0.20`。
5. **失败**：`verified_failure == 0`，且没有新增 capability/routing 归因失败。
6. **成本**：`avg_tokens(child) / avg_tokens(parent) <= 1.20`。
7. **模型档位**：若候选把 `model_tier` 从 standard 提到 strong，必须额外人工确认。

任一条不满足：
- 样本不足 → 保持 probation，可继续 trial；
- 其它硬门槛失败 → `probation → retired`，写 `rsi_trial` 报告与拒绝原因。

### 3.4 批准流程

1. R3.1 把节点置为 probation 后，星图节点显示「开始试用」。
2. 所有者选择 scope 与 max_n，启动 trial；界面显示「试用中」与已收集样本数。
3. 达样本门槛后，runtime 生成 trial report，节点显示「申请晋升」。
4. 审批卡必须同时展示：
   - diff（只改了哪个维度）；
   - R2.2 隔离验证结论（verdict、样本量、Wilson 区间）；
   - trial 报告（成功率、返工率、verified_failure、成本对比）；
   - 拒绝/继续试用/批准三个动作。
5. 动作语义：
   - **批准**：`probation → active`，写 `rsi_approval` 报告；
   - **拒绝**：`probation → retired`，保留证据，不复活；
   - **继续试用**：延长 trial，最多到 `max_n`；
   - **停止试用**：保持 probation，不晋升，证据保留。
6. 默认必须人工批准。只有显式设置 `YOAI_RSI_AUTO_PROMOTE=1` 才允许自动批准，
   且该开关只用于离线实验，不作为生产默认。

### 3.5 命令与消息

| 命令 | 用途 |
|---|---|
| `rsi.trial_start` | 启动 trial：`node_id`, `scope`, `max_n` |
| `rsi.trial_stop` | 停止 trial：`trial_id` |
| `rsi.trial_report` | 请求当前 trial 报告 |
| `rsi.promote_active` | 人工批准后执行：`node_id`, `approval_id`, `reason` |
| `rsi.reject` | 拒绝并退役：`node_id`, `reason` |

消息：`trial.state`、`trial.report`、`approval.recorded`。
报告 `kind`：`rsi_trial`、`rsi_approval`。

### 3.6 验收标准

1. probation 节点在 trial 之外不被路由选中；
2. trial 证据不进 `validation_set()`，不污染 R2.2；
3. child/parent 同题成对，trial 报告可复现；
4. 样本不足只能继续试用，不能晋升；
5. 硬门槛失败自动 retired，无法批准；
6. 未人工批准时，`rsi.promote_active` 必须拒绝；
7. 批准后只到 active，不触发任何源码/权重修改；
8. `YOAI_RSI=0` 时 trial 与晋升全部停止。

> **R3.2 已实施（2026-11-26）**：`TrialStore` / `TrialController` 管理试用批次；
> `SAMPLE_TRIAL` 与 `trial_id`/`trial_role` 隔离 trial 证据；`ExpertRouter.set_trial`
> 支持 tag scope 临时路由；runtime 接 trial_start/stop/report/promote_active/reject；
> 星图 probation 节点显示开始试用/报告/批准/拒绝。合成 smoke 中 temporal 从 probation
> 经 trial 硬门槛和人工批准进入 active，产物 `bench_results/rsi-trigger-smoke/trial_smoke_summary.json`。
> 注意：smoke 的成对 trial 证据由脚本生成，真实会话的 parent 后台影子运行仍是下一步。

## 四、active 监控与回滚

Active 节点进入正常路由，与父节点共同作为候选，由指纹决定选中谁。

滚动监控（30 天）：
- 成功率 Wilson 上界低于父节点 -10pp；
- 返工率 ≥25%；
- verified_failure 出现；
- 平均 token 超过父节点 +20% 且无明确准确率收益。

命中任一：
- `active → retired`；
- 路由自动回退到 parent（无 parent 则 root）；
- 写 `rsi_rollback` 报告；
- 星图标明「已退役 / 已回滚」，保留原节点可审计。

## 五、审批与安全边界

- **improved 自动进 probation 可以；probation 进 active 必须人工批准（默认）**。
- 可选 `YOAI_RSI_AUTO_PROMOTE=1` 打开自动 active，但仅用于离线实验，生产默认关闭。
- 全局 kill switch：`YOAI_RSI=0` 停止触发、验证、晋升；已 active 节点可一键 retired 回退。
- 元策略（阈值/权重）不能改这些硬边界；那是 R4 的事。
- 每次状态迁移必须有报告：证据 id、样本量、CI、成本、审批人/批准方式、回滚目标。

## 六、待实现的命令与数据

| 命令 | 用途 |
|---|---|
| `rsi.promote` | candidate→probation（自动）或 probation→active（需批准） |
| `rsi.trial_start` | 在限定 scope 上把 probation 节点投入小范围试用 |
| `rsi.rollback` | active/probation → retired，回退父节点 |

新增样本类别：
- `SAMPLE_TRIAL = "trial"`：只用于 probation 试用，不进隔离验证集。

新增报告 `kind`：
- `rsi_promotion`
- `rsi_trial`
- `rsi_rollback`

## 七、本方案明确不做

- 不做 improved 直接 active；
- 不做无人值守自动晋升；
- 不做改 Core；
- 不做公网分享或外部上传；
- 不让 retired 复活，恢复走新 candidate。

> **R3.1 已实施（2026-11-26）**：`R3Promoter` 接在 `rsi.validate` 之后。
> improved → probation；regression → retired；no_regression/insufficient 留 candidate。
> 硬门槛：每边界 child/parent 样本 ≥5、单维度 diff、成本 ≤ 父节点 +20%。
> 协议追加 `rsi.promoted`，星图显示晋升/拒绝原因。**probation 仍不进路由，不直接 active。**

> **R3.3 已实施（2026-11-26）**：真实任务命中 running trial 时，主证据标 `trial/child`；
> runtime 用隔离 InMemoryStore + ForcedExpertRouter 后台跑 parent，落 `trial/parent`，不推 UI 事件。
> `RollbackMonitor` 对 active 节点做 30 天滚动回归判定，命中则 retired 并回退父节点，
> 写 `rsi_rollback` 报告与 `rsi.rolled_back` 消息；星图 active 节点可手动「检查回滚」。

## 八、验收标准

1. R2.2 的 temporal smoke（improved）能自动进 probation；
2. multi-session（regression）进不了 probation，直接进入 retired；
3. knowledge-update（no_regression）留在 candidate；
4. probation 节点默认不被路由选中；
5. trial 样本不污染 validation_set；
6. active 触发回滚条件时能回退父节点。
