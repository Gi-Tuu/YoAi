# YoAi 原型审查与 Benchmark 基线建设方案

> 审查日期：2026-11-21　方式：**只读审查**，基于实际仓库代码与已跑测试，不以 README 描述替代代码证据。
> 本次不改任何源码，只输出审查结论与可执行方案。
> 代码根：`E:\agent\YoAi`；内核根：`E:\Competition\YAI Agent Core`（YoAi 强依赖它，见 §一.8）。

---

## 一、YoAi 原型能力现状报告

判定口径：**已实现**（代码完整且有测试或实测）/ **部分实现**（骨架在，但有明确缺口）/ **尚未实现** / **无法确认**。

| # | 能力 | 判定 | 核心证据 |
|---|---|---|---|
| 1 | Agent 主执行循环 | **已实现** | `core.py:532-701`、`kernel/astream.py:59-253`、`kernel/react.py:41-248`、`types.py:43-67`（21 种事件） |
| 2 | 模型适配 | **已实现** | `spi/model.py:10-43`、`llm/openai_compat.py:12-96`、`llm/anthropic.py:206-348`、`llm/fallback.py:73-357`、`yoai/models/gateway_provider.py:25-112` |
| 3 | 工具注册与使用 | **已实现** | `tools/registry.py:18-100`、`discovery/introspect.py:147-216`、`policy/allowlist.py:8-32`、`tools/executor.py:651-829`、`yoai/agent.py:70-75` |
| 4 | 多步骤任务（执行/反馈/终止） | **已实现** | `kernel/planning.py:142-178`、`kernel/react.py:84-248`、`kernel/loop.py:608-705,751-827`、`kernel/budget.py:119-162` |
| 5 | 工作记忆（会话内） | **已实现** | `memory/inmemory.py:10-94`、`kernel/context.py:46-151`、`kernel/compaction.py:181-284` |
| 6 | 长期记忆 | **部分实现** | YoAi `context.py:19-93` + `goals.py:22-105`（简单 KV/目标）；Core `memory/vault.py:158-269,403-568` 更完备但 **`agent.py:57-63` 构造 Core 时未注入 vault → YoAi 未启用** |
| 7 | 跨会话状态持久化 | **已实现** | `yoai/session.py:82-115,158-194`、`context.py:28-59`、`goals.py:31-58`（原子写+损坏隔离）；`memory/sqlite_store.py:242-315,365-425,595-646` |
| 8 | 独立运行能力 | **尚未实现** | `pyproject.toml:9-13` 声明 `dependencies=[]`，但源码 12 处 import `yai_core`、`yoai.spec:11` 硬编码 CORE_SRC、多数测试硬编码 Core 路径 → **绑死 Core 源码目录** |
| 9 | 专家插件 / 进化档案 / 路由 | **部分实现** | `evolution/models.py:18-26,33-63`、`archive.py:93-134,184-225`、`router.py:77-160`、`expert_provider.py:61-110`；**`router.py:84-87` max_performance 抛 NotImplementedError（M3 未实现）**；ExpertSpec 仅 `prompt_suffix` 真正生效，`tools/strategy_bias/tier/budget` 只参与打分不约束执行 |
| 10 | 候选版本评测 | **部分实现** | `evidence/benchmark_lab.py:81-151`（validation 隔离 + Wilson 区间 + 父节点对照 + insufficient 门槛）、`promotion.py:61-144`；**但生产路径 `main_window.py:288` 固定写 `sample_class="evolution"`，validation 样本只存在测试/demo → 真跑评测恒 0 样本、恒 insufficient** |
| 11 | 版本恢复 | **部分实现** | `archive.py:205-225` `restore()` 从 checkpoint 派生新 candidate；**但 `evidence=[]` 未回填、且需重新走 probation/active，非一键回滚** |
| 12 | 日志/轨迹/执行结果 | **部分实现** | `desktop/worker.py:39-81`、`evidence/collector.py:48-96`、`evidence/models.py:27-51`（verification/usage/route_decision 落盘）；**缺口：worker 落盘 `except: pass` 静默吞错；`benchmark_lab._success` 在无验收时回退 `not e.errors`，成功判定偏弱** |

### 关键实现细节（审查员原话要点）

- **主循环**：四策略（direct/react/plan/clarify），21 种事件，终止路径包括正常 DONE、error DONE、预算熔断 DONE、异常救援 DONE；只有用户取消不发 DONE。内核完整，YoAi 是门面（`agent.py:77-85` 纯透传）。
- **工具**：`discover(capabilities)` 用 PEP 484 内省出 6 个个人工具（`capabilities.py:16-48`），`llm_schema()` 转 OpenAI function 形状；权限闸真实生效（allow_all 默认，ASK 走审批）；工具结果经 `wrap_tool_output` 标为不可信数据后回灌。
- **记忆**：Core 的会话工作记忆（history + compaction）与 YoAi 的长期 KV/目标**两套并存但未打通**；Core MemoryVault 具备语义召回、去重、容量淘汰、owner 隔离，但 YoAi 没开。
- **进化**：M1 指纹路由真实注入 `prompt_suffix`（`expert_provider.py:100`），无可靠候选回退 active 根节点；M2 候选生成+晋升门+审计齐备；**但没有生产验证样本，进化链在真实使用中不会晋升任何节点**。

---

## 二、Benchmark 就绪度矩阵

三份 Benchmark 的官方协议已逐一核查（来源见 §六），**不强行统一指标**，各自保留原始评分口径。

| 维度 | LoCoMo | LongMemEval | GAIA |
|---|---|---|---|
| 官方来源 | `github.com/snap-research/locomo` | `github.com/xiaowu0162/LongMemEval` | `huggingface.co/datasets/gaia-benchmark/GAIA`（GitHub 仓库已 404） |
| 数据获取 | 仓库内 `data/locomo10.json`，公开 | HF `xiaowu0162/longmemeval-cleaned`，wget 3 个 json，公开 | HF **gated**，需同意不转存条款；Parquet 格式 |
| 规模/类型 | 10 段长对话，QA + 事件摘要 + 多模态对话生成 | 500 题，5 类：信息抽取/多会话推理/知识更新/时间推理/弃用；S≈115k tokens，M≈500 会话 | 466 题（validation 166 / test 300），3 个 level，工具使用/多步推理/文件处理 |
| 官方评分程序 | 有：`scripts/evaluate_gpts.sh` 等 + `task_eval/` | **有独立可本地跑的 `src/evaluation/evaluate_qa.py`**（输入 jsonl：`question_id`+`hypothesis`）+ `print_qa_metrics.py` | **无公开本地评分脚本**；validation 答案公开可自算 accuracy，test 答案隐藏须提交 HF leaderboard 服务端评分 |
| 评分指标 | QA 用 F1/BLEU（见 `task_eval/`，以官方脚本为准）；事件摘要另有口径 | LLM-as-judge 自动判分 + 记忆召回准确率（session/turn 级） | exact match / accuracy，按 level 分报 |
| 是否需上传 | 否，本地跑 | 否，本地跑评分脚本 | test 需提交 leaderboard；validation 可本地 |
| YoAi 接入条件 | **部分具备**：有跨会话持久化 + SQLite 历史；缺批量对话灌入与评测入口 | **部分具备**：同上；缺长历史在线记忆与 jsonl 输出器 | **不具备**：无网页搜索/文件解析/多工具编排，无附件处理 |
| 主要缺口 | 无批量 QA 驱动器；无时间/多跳结构化记忆召回；无 F1 评分器 | 无在线增量记忆（现在是一次性会话历史回放）；无 abstention 处理；无 LLM judge 调用 | 缺 Level 1 所需 web 搜索、代码/文件工具；缺附件输入通道；无提交格式生成器 |
| 需新增适配器 | `LoCoMoAdapter`（对话回放→YoAi 会话、QA→任务、答案收集）、F1 打分桥接 | `LongMemEvalAdapter`（haystack→会话注入、hypothesis 落 jsonl）、官方评分脚本调用器 | `GAIAAAdapter`（题目+附件→任务、答案提取）、web/文件工具集、leaderboard 提交器 |
| 本地资源 | 10 对话 QA 数百题，每题一次模型调用；CPU 可跑，需 API key | 500 题 + 115k token 长上下文；LLM judge 另需调用；建议 S 集先跑 | 需联网搜索与文件工具；图像/PDF 附件解析；成本最高 |
| 成本估算（按实测 deepseek flash） | 单题约 300–1800 tokens（ROUND1 实测单轮 355 / 工具轮 1843）；数百题量级约 0.1–1M tokens，免费额度内可试 | S 集每题需灌 115k token 历史 → 500×115k≈5750 万 tokens，**免费 flash 不现实**，须 oracle 集或长上下文模型/检索基线 | 每题多步工具调用，Step 数×1843 tokens；需另加搜索 API 成本；最高 |
| 最小路径 | **最快**：本地直跑官方脚本，先复制其 QA 流程用 YoAi 回放 10 对话 | **次快**：先用 `longmemeval_oracle.json`（只含证据会话，短）+ 官方 `evaluate_qa.py`，绕开 115k 长历史 | **最慢**：先补 web/文件工具，再跑 validation 166 自评；暂不碰 leaderboard |

> 成本数字来自 `docs/ROUND1-REAL-MODEL-TEST.md` 的真实调用（算里 deepseek flash：91/355/1843/3797 tokens），外推为量级估算，非官方报价。

---

## 三、第一批实施清单（P0/P1/P2）

| 优先级 | 事项 | 依赖 | 产出 |
|---|---|---|---|
| **P0-1** | 建独立 `bench/` 适配层骨架（注册、配置快照、结果落盘），不碰 `src/yoai/` 执行逻辑 | 无 | 评测入口 `python -m yoai_bench run --benchmark ...` |
| **P0-2** | LongMemEval 最小闭环：下载 oracle 集 → 写 hypothesis jsonl → 跑官方 `evaluate_qa.py` | P0-1；HF 数据集可下 | **第一个真实可复现成绩**（本地自评） |
| **P0-3** | 修复生产验证样本缺口：给 BenchmarkLab 一条明确的 validation 注入路径（评测专用，不进日常对话） | P0-1 | 进化晋升在真实数据上可发生 |
| **P0-4** | 评测元数据完整记录：模型版本、数据版本、运行配置、随机种子、每任务 token/latency/调用次数 | P0-1 | 可追溯结果 |
| **P1-1** | LoCoMo 适配：对话回放 + QA 驱动 + 官方 task_eval 桥接 | P0-1 | 第二个成绩 + 长期记忆对照 |
| **P1-2** | 状态断言器扩展：覆盖"回忆/查询/知识更新"目标（当前只认"记住 X 是 Y"） | 无 | 验收不再把回忆任务判 partial |
| **P1-3** | 真实模型跑通 M2 进化链（真证据→候选→隔离评测决策） | P0-3 | 进化树真实验证 |
| **P2-1** | GAIA Level 1 适配 + web/文件工具集 | 新增工具，工作量大 | GAIA validation 自评 |
| **P2-2** | GAIA test 提交 leaderboard | P2-1；账号申请 | 公开榜单成绩 |
| **P2-3** | M3 最高性能模式（有预算的候选试验） | `router.py:84-87` 当前 NotImplementedError | 完整进化机制 |

---

## 四、最小评测架构方案

**原则**：独立适配层，不改 `src/yoai/` 执行逻辑；复用已有 `EvidenceStore` / `ExecutionEvidence` / `BenchmarkLab`；各 Benchmark 保留原始评分口径。

```
E:\agent\YoAi\
  bench/                          # 新增，独立包（不进桌面默认路径）
    __init__.py
    registry.py                   # Benchmark 注册与选择（name→adapter 类）
    base.py                       # BenchmarkAdapter 协议：load / to_task / collect / score
    config.py                     # 运行配置快照：模型/参数/工具/数据版本/seed
    runner.py                     # 编排：加载→逐题执行→收集→调官方评分→落原始结果
    adapters/
      locomo.py                   # 10 对话回放 + QA + 调 scripts/task_eval
      longmemeval.py              # haystack→会话；输出 jsonl；调 evaluate_qa.py
      gaia.py                     # 题目+附件→任务；validation 自评/test 提交
    io/
      evidence_bridge.py          # 复用 EvidenceStore/ExecutionEvidence，写执行轨迹
      result_store.py             # 原始输出 + 官方评分 + 元数据，JSONL/JSON
    compare.py                    # 多次运行比较（按 config hash / seed 分组）
  data/                           # 不入库：benchmark 数据软链或下载目录
  results/                        # 不入库：每次运行一个子目录（含 config.json + raw + score）
```

**数据流**：
```
官方数据集 → adapter.load(数据版本校验)
          → adapter.to_task(题) → YoAiAgent.astream(任务) [模型/工具/参数来自 config 快照]
          → ExecutionEvidenceCollector 采 DONE/verification/usage/route_decision
          → adapter.collect → hypothesis 文件（各 Benchmark 规定格式）
          → adapter.score → 调官方评分脚本（不自行实现评分）
          → result_store 落盘（模型版本/数据版本/config/seed/原始输出/官方分数/token/latency）
          → compare 按 config+seed 比较多次运行
```

**接口草签**（仅设计，不实现）：
- `BenchmarkAdapter.load(split) -> Iterator[Case]`
- `BenchmarkAdapter.to_task(case) -> TaskInput`（含历史注入方式）
- `BenchmarkAdapter.format_prediction(case, result) -> dict`（写入官方要求的 jsonl 字段）
- `BenchmarkAdapter.official_score(pred_file, data_file) -> ScoreReport`（subprocess 调官方脚本）
- `RunConfig.snapshot() -> dict`（模型名+版本、temperature、工具集、数据文件 hash、seed）

**明确不做**：不把评测流程塞进 `desktop` 默认路径；不改 Core 内核；不为统一指标改写任何官方评分。

---

## 五、自进化专项评测设计

### 5.1 原型已实现的部分（对照你的 8 条机制）

| 机制 | 状态 | 证据 |
|---|---|---|
| 保留历史专家版本 | 已实现 | `archive.py:93-134` 节点持久化为 JSON |
| 执行前按任务选历史节点 | 已实现 | `router.py:77-127` + `expert_provider.py:61-74` |
| 高效模式直接选专家 | 已实现 | `router.py:77-127` efficient 路由 |
| 最高性能模式有限预算候选试验 | **尚未实现** | `router.py:84-87` `NotImplementedError` |
| 每次正式任务由一个专家执行 | 已实现 | `expert_provider.py:90-110` 每次 achat 前路由 |
| 默认以本次执行节点为父节点 | 已实现 | `candidate.py:56-129` parent=evidence.expert_id |
| 新分支独立评测后晋升 | 部分实现 | `promotion.py:61-144` 门控在，**但生产无 validation 样本 → 恒 insufficient** |
| 父节点保留可重新参与路由 | 已实现 | archive 不删除节点；`router.py` 按 active 状态筛选 |

### 5.2 四组对照实验设计

统一底层模型（同一 deepseek 版本）、同一数据切分（train/validation/test 严格隔离）、同一运行预算（max_iters / token / 工具调用次数固定）。

| 组 | 配置 | 问题 |
|---|---|---|
| **A 固定 Agent** | 单一根节点专家，无路由、无进化 | 基线能力 |
| **B 线性自进化** | 只保留最新节点，新版本覆盖旧版本 | 有无灾难性遗忘 |
| **C 保留分支但不自适应路由** | 多节点都在，但执行固定选根/随机选 | 分支本身是否有价值 |
| **D YoAi 完整机制** | 指纹路由 + efficient 选专家 + M2 候选晋升 | 自适应路由净收益 |

### 5.3 关注指标与判定

- **未见任务成功率**：以 test 集成功率为主指标，Wilson 区间报置信度（复用 `benchmark_lab.wilson_interval`）。
- **旧能力保留**：在历史任务子集上复测，比较 A/B/D 的回退幅度（B 应最差）。
- **跨任务泛化**：新能力在**不同指纹标签**任务上的成功率提升，而非仅在训练指纹上。
- **路由质量**：D 相对 C 的提升 = 路由净收益；记录每次 `route_decision`（已有落盘）。
- **单任务成本**：token / 调用次数 / 延迟，来自证据 `usage` 与执行计时。
- **版本恢复可用性**：从 checkpoint 恢复后，在新任务上是否达到原版本水平（当前恢复需重新晋升，要计入成本）。

**晋升判定**：沿用 `PromotionGate` 口径——validation 集上 Wilson 下界优于父节点且样本量达标 → probation；有限试用无失败 → active；退化 → retired。**严禁使用 evolution 样本自评晋升**（现有隔离机制必须保留）。

**本阶段只完成设计，不实现全部进化评测**；先做 A vs D 两组的 P0 对照。

---

## 六、验证记录（已实际运行）

| 检查项 | 命令/方式 | 结果 |
|---|---|---|
| 全量测试 | `pytest -q`（offscreen） | **160 passed, 34 warnings** |
| 真模型连通性 | `SuanliAdapter.send()` | HTTP 200，"测试收到"，91 tokens |
| 真模型单轮对话 | `YoAiAgent.astream` + 算里 | direct 路由、自然回答、证据落盘、355 tokens |
| 真模型工具调用 | 同上 | 主动调 `remember_fact(咖啡偏好=美式)`、真实落盘、`verified_success`、1843 tokens |
| 真模型多轮工具链 | 同上 | 记住城市→`list_facts` 查证→正确回答，3797 tokens |
| Benchmark 官方协议 | WebFetch/WEB 搜索 | LoCoMo README、LongMemEval README 直读成功；GAIA GitHub 404、leaderboard fetch 失败 → 改用 HF 数据集 README + 搜索交叉确认 |
| 文档/代码一致性抽查 | 3 项里程碑测试计数 | M1=14、M2=12、Verifier=14 与文档吻合 |
| 未验证项 | 原因 | ① 三个 Benchmark **均未实际下载数据或跑分**（本阶段只读审查，且 GAIA gated）② 未跑真模型 M2 进化链 ③ 未验证 Core MemoryVault 接入后的效果 ④ GAIA leaderboard 服务端评分机制未能直读页面，结论来自 HF 数据集 README 与搜索 |

---

## 七、三个问题的明确回答

### Q1：YoAi 当前最接近可以正式测试的 Benchmark 是哪个？

**LongMemEval（先用 oracle 集）。** 理由：
1. 官方提供**独立本地评分脚本** `evaluate_qa.py`，只需 `question_id` + `hypothesis` jsonl，不需要上传服务器、不依赖 Leaderboard 账号（LoCoMo 也有脚本但其 F1 口径与事件摘要分散；GAIA test 必须提交服务端且数据 gated）。
2. YoAi 已有**跨会话持久化**（`session.py:82-194`）与 `EvidenceStore`，最接近"把历史喂进去、答题、对答案"的形态。
3. 用 `longmemeval_oracle.json`（只含证据会话）可绕开 S 集 115k token 长上下文，在免费 deepseek flash 上成本可控；S/M 全量长上下文才是真正难点。

### Q2：为了获得第一个真实且可复现的 Benchmark 成绩，最少需要做哪些工作？

**最小 5 步**：
1. 下载 HF `longmemeval-cleaned` 的 `longmemeval_oracle.json`（公开、免申请）。
2. 写一个**约 100 行的薄适配器**：把每个 instance 的 `haystack_sessions` 作为历史灌入一个独立会话，把 `question` 作为任务调 `YoAiAgent.astream`，取 `DONE.final_text` 作为 `hypothesis`，按 official 格式写 jsonl。
3. 写一个**运行配置快照**：记录模型名/版本、数据文件 hash、max_iters/token/工具预算、seed、时间戳，随结果落盘。
4. 直接调用官方 `src/evaluation/evaluate_qa.py` 评分（不自行实现 judge），再用 `print_qa_metrics.py` 汇总；保留原始 log。
5. 把 output + config + score + token/latency 存入 `results/<run_id>/`，可复现。

**不需要**：改 Core、改 YoAi 执行逻辑、实现新工具、等 GAIA 账号、跑 115k 长上下文。

### Q3：现阶段应优先提升基础 Agent 能力，还是开始建设进化树评测？

**优先提升基础 Agent 能力**，但**同步建设最小评测入口（P0-1/P0-2）**。理由基于源码：

1. **进化的产物在真实路径上无法晋升**：`main_window.py:288` 把日常对话全标为 `evolution`，`benchmark_lab.evaluate` 只认 `validation` 样本（`benchmark_lab.py:83`），生产环境 validation 样本为 0 → 任何候选评测恒 `insufficient`（`benchmark_lab.py:95-96`）→ `PromotionGate` 永不晋升。**在补上验证样本入口前，进化树评测测的是空转。**
2. **ExpertSpec 的真实作用面很窄**：`expert_provider.py:100` 只注入 `prompt_suffix`；`tools`、`strategy_bias`、`model_tier`、`budget` 在路由里只是打分信号，没有真正约束执行（`router.py` / `expert_provider.py`）。即使 D 组跑出来，差异也主要来自提示词，不足以验证"专家分支"的价值。
3. **最高性能模式尚未实现**：`router.py:84-87` `max_performance` 直接抛 `NotImplementedError`，5.2 里 D 组的"有限预算候选试验"无法执行。
4. **验收覆盖不全**：`context_assertion.py:33-73` 只覆盖"记住 X 是 Y"，回忆/知识更新类返回 `not_verifiable`（真模型实测回忆任务因此判 partial，见 `ROUND1-REAL-MODEL-TEST.md`）。基础验收不准，进化评测的成功率就不可信。
5. **依赖关系**：`pyproject.toml:10` 声明零依赖但实际绑死 Core 源码路径（`yoai.spec:11`、12 处 import），评测要可复现必须先固定这个依赖边界。

**建议节奏**：先用 P0-2 拿到 LongMemEval oracle 的真实成绩（建立基线与可复现链路）→ 补 P0-3 验证样本入口与 P1-2 验收覆盖 → 再让 D 组进化对照有意义。**没有可靠基线，进化收益无从谈起。**

---

> 本报告所有结论均可追溯到上述 `path:line` 证据或已跑测试；Benchmark 的规模、协议、评分方式来自官方 README 核查，未编造任何成绩或榜单数据。
