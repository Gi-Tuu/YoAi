# RSI 产品化研究：把进化树从骨架做成真正卖点（2026-11-26）

> 定位修正：RSI（Recursive Self-Improvement）是这个智能体的核心买点，进化树是刻意做的差异化。
> 因此研究目标不是「证明已有 RSI」，而是设计一条**能真正落地、可审计、不伤害体验**的 RSI 路径。
> 归属判断：全部在 YoAi 侧（UI/runtime/证据/档案），**Core 零改动**；不把依赖 Core 当缺陷。

## 一、先定义 YoAi 语境下的 RSI

不采用「模型自己改权重/改源码」这种不可控定义。YoAi 的 RSI 定义为：

> 系统在使用中持续采集真实反馈，稳定识别出自身能力边界；
> 自动生成最小、可逆、版本化的能力配置候选；
> 在隔离验证中证明改进后才晋升；
> 退化自动回滚；
> 并且「决定如何进化」的策略本身也可被版本化和改进。

关键词：**使用中采集、稳定信号、最小可逆候选、隔离验证、晋升/回滚、元策略可进化**。
不是每次对话换个提示词，也不是跑一次 benchmark 生成一个节点。

## 二、现有资产盘点（足以做地基）

| 资产 | 位置 | 作用 |
|---|---|---|
| 执行证据 | `src/yoai/evidence/` | 真实事件流落盘：指纹、标签、工具调用、usage、verification、errors |
| 三分归因 | `evidence/attribution.py` | capability / routing / environment / none |
| 任务指纹 | `evolution/fingerprint.py` | 把任务映射到能力标签与稳定 key |
| 进化档案 | `evolution/archive.py` | 节点、血统、生命周期、checkpoint、证据索引 |
| 候选生成 | `evolution/candidate.py` | 从归因生成确定性候选（当前只补工具/标签/提示） |
| 晋升门 | `evolution/promotion.py` | candidate→probation→active、insufficient/regression 不晋升 |
| 生产旁路 | `runtime/yoai_runtime.py` | `YOAI_EVOLUTION=1` 时调用 `EvolutionEngine.evolve` |
| 报告持久化 | `evolution/reports.py` | 每次进化尝试可审计 |
| 星图 | `GalaxyPage.tsx` | 展示节点、血统、生命周期、证据链与晋升理由 |
| 用户动作 | `MessageActions.tsx` | 复制/编辑/撤回/分享/重新生成——**目前还没接入进化链** |

已有的是「可审计的实验台」；缺的是「使用信号→触发→验证→晋升→回滚」的自动闭环。

## 三、缺的六块（按优先级）

### 1. 用户反馈信号没有进证据链
刚做的编辑/撤回/重新生成/分享/复制是天然反馈，但目前只改 UI 和会话分支，
没有写进 `ExecutionEvidence`。因此系统不知道「哪条回答被返工了」。

需要新增 `FeedbackSignal`：
- 来源：retract / edit / regenerate / copy / share / 继续追问 / 会话放弃；
- 绑定：`evidence_id`、`run_id`、`session_id`、能力标签、是否正向；
- 规则：同一任务多次 regenerate 是强负信号；copy/share 是弱正信号；编辑提问是意图校正信号。

### 2. 成功判据太窄
现在主要靠 `verification` 和任务 status。真实体验里「答完但用户不满意」不算成功。
需要把「完成且无返工」作为复合成功判据：
`success = verified_ok AND no_rework_within_window AND not_abandoned`。

### 3. 没有能力边界看板
`BenchmarkLab` 只在实验脚本里按标签算。生产需要一张滚动看板：
每类能力标签的任务量、成功率、返工率、平均 token、Wilson 区间。
触发依据是**边界统计**，不是单次失败。

### 4. 触发规则尚未定义
建议默认规则（可配置）：
- 某标签近窗口（如 7 天）样本 ≥ 20；
- 成功率 Wilson 上界 < 全局基线 - 10pp，或返工率 > 基线 + 15pp；
- 三分归因里 capability/routing 占比 ≥ 60%，environment < 20%；
- 冷却期内没有同方向候选。
满足才生成候选；否则明确记录「不进化」及原因。

### 5. 候选空间太窄
当前候选只加工具白名单/标签/提示。RSI 的候选维度应扩展到：
- `tools`：补工具（保持基础工具集，不再做「越窄越专业」）
- `prompt_suffix`：结构化策略提示（先核对状态、按时间排序、跨会话汇总）
- `model_tier`：standard/strong 切换（成本受预算约束）
- `budget`：模型/工具调用上限
- `strategy_bias`：direct/react/plan/clarify
- `memory_policy`：检索工具优先级（YoAi 侧）
- `plugin`：候选插件在 shadow 模式试用（不自动执行未验证代码）
一次只改一个维度，diff 可解释、可回滚。

### 6. 没有 shadow 验证与回滚
现在候选直接写档案，但生产路由只认 active，验证样本又不足。
需要：
- 候选先入 `candidate`，不进生产路由；
- 用 held-out validation 集做 child/parent 成对验证；
- 样本不足就保持 candidate（诚实，不制造 verdict）；
- 显著改进才 probation→active；
- active 后监控回归，触阈值自动 retired 并回退 parent。

## 四、元递归（真正「Recursive」的部分）

只让系统改进专家配置还不够。要让 RSI 名副其实，第二层是：

> 「触发阈值、候选维度权重、验证样本量、晋升门槛」本身也作为版本化配置存在，
> 可以被同样的证据链评估和改进。

但要严格限制：
- 元策略只能改**阈值和权重**，不能改安全边界（最小样本、回滚条件、审计要求）；
- 元策略改动必须人工批准后才能生效；
- 每一代元策略有 checkpoint，可回退。

这样才有「递归」含义，同时不会滑向不可控自修改。

## 五、落地路线（建议按阶段推进）

| 阶段 | 目标 | 交付 | 是否自动生效 |
|---|---|---|---|
| R0 信号采集 | 用户动作进证据链 | `FeedbackSignal`、runtime 命令、快照字段、测试 | 否（只采集） |
| R1 边界看板 | 看见能力边界 | 滚动统计、Wilson 区间、星图热区 | 否（只看） |
| R2 shadow RSI | 自动生成候选并隔离验证 | TriggerEngine、候选维度扩展、BenchmarkLab 成对验证 | 否（shadow） |
| R3 受控晋升 | 显著改进才晋升 | PromotionGate 接自动回滚、人工批准开关 | 可配置，默认人工批准 |
| R4 元递归 | 元策略版本化 | 阈值/权重的 checkpoint 与评估 | 必须人工批准 |

## 六、安全边界（不可协商）

- 不改 Core；不自动改产品源码；不自动更新模型权重。
- 候选只能是配置/提示/插件开关，且版本化、可回滚。
- 验证样本与进化样本隔离；不允许用用户真实任务当未批准的验证集。
- 最小样本、回滚阈值、审计日志是硬边界，元策略不能改。
- 全局 kill switch：一个开关关闭所有自动进化，已有 active 节点可回退。
- 用户可见：星图必须解释「为什么变、证据是什么、什么时候回滚」。

## 七、衡量指标

- 成功率、返工率、平均完成时间、token 成本（按能力标签）。
- 晋升精确率：晋升后 7 天是否仍优于父节点。
- 回滚率：晋升后触退化的比例。
- 「无进化率」：系统判断不该改的比例——这是保守性的健康指标，越高不代表越差。
- 用户信任信号：查看星图/进化说明的频次、是否手动回退。

> **R0 已实施（2026-11-26）**：`FeedbackSignal` / `FeedbackStore` 落 `evidence/feedback.jsonl`；
> runtime 接 `feedback.record`，按 run_id 或任务文本绑定执行证据；前端消息动作条
> （复制/分享/编辑/撤回/重新生成）全部上报。**只采集，不触发进化**。
> 协议 v1 追加 `feedback.record` / `feedback.recorded`，三份 runtime 已同步。

> **R1 已实施（2026-11-26）**：新增 `boundary.get` / `boundary.state` 与左侧导航「边界」页。
> 看板展示近 30 天每个能力标签的样本数、成功率、Wilson 区间、返工率、平均 token、
> 正向信号、相对基线与状态分级。**只统计，不触发进化**。
>
> **阈值定版 v1（常见比例监控做法）**：样本 <20 不下结论；返工率 ≥15% 进观察、
> ≥25% 进薄弱；成功率 Wilson 上界低于基线 10pp 以上也进薄弱；点估计低 5pp 进观察。
> 10pp 是实际显著性门槛，20 样本是比例估计的最低可接受量。

> **R2.1 已实施（2026-11-26）**：新增 `TriggerEngine` 与 `rsi.trigger` / `rsi.triggered`。
> 触发条件：样本 ≥20、边界 weak、能力/路由归因 ≥60%、环境归因 <20%、7 天冷却。
> 候选只写 `EvolutionArchive` 的 `candidate` 节点，一次只改一个维度（工具/提示/标签），
> 写 trigger 报告并在星图可见。**不进路由、不晋升、不自动生效**。

> **R2.1 手动 smoke（2026-11-26）**：真实边界样本不足，先用合成场景跑了一批候选，
> 产物在 `bench_results/rsi-trigger-smoke/`，脚本 `bench/run_rsi_trigger_smoke.py`。
> 三条候选分别验证能力补工具、路由补标签、能力补提示，全部 `candidate` 生命周期。
> **这是流程 smoke，不是产品证据，也没有写进生产档案。**

> **R2.2 手动 smoke（2026-11-26）**：`bench/run_rsi_validation_smoke.py` 把 R2.1 的
> 三个候选接进 child/parent 隔离验证。结果：temporal `improved`、multi-session `regression`、
> knowledge-update `no_regression`；全部 `promoted=false`，生命周期仍为 candidate。
> 产物在 `bench_results/rsi-trigger-smoke/validation_summary.json`。
> **合成 smoke，不是产品证据，不晋升。**

> **R3 晋升方案已定（2026-11-26）**：见 `RSI-PROMOTION-PLAN.md`。
> 核心口径：improved 只自动进 probation；probation → active 需 trial ≥20 条、无返工/成本退化并人工批准；
> active 退化自动 retired 并回退父节点。retired 终态，不复活。

## 八、第一个具体实验（基于 R0/R1 数据做）

**题目：时间推理类任务的返工信号是否能稳定触发能力候选？**

1. 采集两周内 temporal 标签任务的用户 regenerate/edit/retract 信号；
2. 计算返工率与成功率 Wilson 区间，与全局基线对照；
3. 若达到阈值，生成「时间排序提示 + 核对事件时间」候选；
4. shadow 模式用 held-out 验证题跑 child/parent 成对 A/B；
5. 只有显著改进才申请晋升；否则记录「不进化」。

这个实验如果失败也有价值：说明用户的返工信号不能作为 RSI 触发源，应换信号或换边界。

## 九、诚实结论

当前进化树不是 RSI，但它是**少数真的把证据、血统、门控、审计、可视化都搭起来的 RSI 地基**。
把它变成卖点，不缺再写一个 prompt，而缺三件事：

1. 把用户真实反馈接入证据链；
2. 用统计门槛而不是单次失败触发；
3. 在隔离验证通过后才允许生效，并且随时可回滚。

做完这三件，RSI 才会从「可视化故事」变成「可验证的产品行为」。
