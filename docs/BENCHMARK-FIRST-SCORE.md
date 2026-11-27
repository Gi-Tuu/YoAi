# 第一个真实 Benchmark 成绩 · LongMemEval oracle（YoAi）

> 运行日期：2026-11-21　状态：**已完成，评分可复现**
> 这是 YoAi 第一次用真实模型、真实数据集、官方评分口径跑出的 Benchmark 分数。
> 所有原始输出、配置、评分日志见 `bench_results/lme-oracle-final/`。

## 评分结果（全量 500 题 · 最终）

| 指标 | 数值 |
|---|---|
| **总体准确率（官方口径）** | **345 / 500 = 69.00%**（Wilson 95% CI：64.8%–72.9%） |
| 题量 | **500（全量 oracle 集，全部唯一）** |
| 答案模型 | `deepseek/deepseek-v4.1-flash-1017`（算里免费） |
| Judge 模型 | `deepseek/deepseek-v4.1-flash-1017`（官方为 gpt-4o，见口径说明） |
| 相对基线 | 64.20% → **69.00%（+4.8pp）**，来自 question_date 时间锚点注入 |

### 全量分题型（最终 vs 基线）

| 题型 | 最终 | 基线 | 变化 |
|---|---|---|---|
| single-session-user | **100.0%** (70/70) | 97.1% | +2.9pp |
| single-session-assistant | **98.2%** (55/56) | 100.0% | -1.8pp |
| knowledge-update | **92.3%** (72/78) | 91.0% | +1.3pp |
| single-session-preference | **93.3%** (28/30) | 90.0% | +3.3pp |
| temporal-reasoning | **54.9%** (73/133) | 37.6% | **+17.3pp** |
| multi-session | **35.3%** (47/133) | 36.8% | -1.5pp |

**关键**：提升几乎全来自 temporal-reasoning（补了 question_date 时间锚点）。
multi-session 仍是 35%——它需要的是跨会话关联能力（见下方记忆层改造），不是时间锚点。
两版全量结果都保留：`lme-oracle-full500/`（基线 64.2%）、`lme-oracle-full500-v2/`（最终 69.0%）。
60 题样本（71.67%）高估真实水平的结论仍成立。

### 修复前后对比

| 项 | 修复前 | 修复后 |
|---|---|---|
| 总体准确率 | 66.67% (40/60) | **71.67% (43/60)** |
| 异常答题 | 13（11 伪工具调用 + 2 reasoning 截断） | **0** |
| 抽样重复 | 3 题重复 | **0（无放回抽样）** |
| single-session-preference | 70% | **100%** |
| knowledge-update | 70% | 80% |
| temporal-reasoning | 40% | 20%（样本变化，见下） |
| multi-session | 20% | 30% |

提升来自三处修复（详见"工程修复"节）：role 结构保留 + 反工具标记指令、
思考模型 max_tokens/reasoning 回退、分层抽样去重。总提升 5 个百分点看似不大，
是因为修复前 13 道异常题里有 2 道被 judge 误判为 yes；修复后这些"蒙对"没了，
换成了 60 道干净的答题。真实能力信号更可信。

## 口径说明（必须如实标注）

1. **评分 prompt 与判定逻辑逐字保留官方**：6 类题型的 `get_anscheck_prompt` 模板、
   弃用问句模板、`yes/no` 判定、`temperature=0` 全部照搬官方 `evaluate_qa.py`。
2. **Judge 模型替换为 deepseek**：官方用 `gpt-4o-2024-08-06`，本机无 OpenAI key
   且算里网关无 gpt 模型，故 judge 用同一款免费 deepseek。**此分数不可与官方榜单直接对比**。
3. **max_tokens 适配**：官方 judge 用 10，deepseek 是思考模型（10 token 只够 thinking、
   content 为空），本地放大到 256 并回退 `reasoning_content`。评分 prompt 本身未改。
4. **评分器已校准**：用 ground truth 作 hypothesis 跑 60 题，非 preference 类 49/50 = 98%
   （1 题 judge 固有误差）。preference 类的 `answer` 是评分 rubric 而非标准答案文本，
   不能拿来校准（详见"评分器校准"节）。评分器可信。
5. **数据集**：`longmemeval_oracle.json`（官方 HuggingFace，15.4MB），sha256 记录在 config.json。

## 执行口径（输入适配，不改评分）

- oracle 集每题的 `haystack_sessions` 灌入 Core `SqliteStore` 作为历史，每条消息带 session 日期前缀（保留时间线索）。
- 纯记忆 QA 清空工具注册表 → router 硬规则强制 direct，避免工具调用误判干扰。
- 每题独立临时 SQLite / data_dir，互不污染。
- 分层抽样 seed=20261121，每类 10 题，可复现。

## 工程修复（2026-11-21 第二轮）

修复前 13 题失败，逐题诊断后定位三处根因，均在 `bench/` 评测侧修复，**未改 Core、未改 `src/yoai` 执行逻辑**：

1. **伪工具调用（11 题）**：deepseek 在历史里看到 XML 标记后，把答案写成 `<tool_call>` 文本，
   被 Core 协议守卫 `_looks_like_raw_tool_call` fail-closed 拒绝（这是 Core 的正确行为，不该改）。
   根因是 `BenchModelProvider._render` 把所有消息拼成一个 user 串，破坏了 system/user/assistant 角色结构。
   修复：保留原始 role 结构 + 末尾追加"只回答、不要输出工具标记"的 system 指令 → 11 题归零。
2. **reasoning 截断（2 题）**：deepseek 思考模型的答案在 `reasoning_content`，`max_tokens` 太小只够思考。
   修复：答题侧 1024 / judge 侧 256 + content 为空时回退 reasoning_content。
3. **抽样重复（3 题）**：分层抽样同一 bucket 有放回抽取导致重复。修复为无放回抽样，60 题全唯一。

修复后：异常 0、重复 0、成绩 66.67% → 71.67%。

### 评分器校准（第二轮）

用 ground truth 作 hypothesis 跑 60 题校准：非 preference 类 **49/50 = 98%**（1 题 judge 误判，
为 deepseek judge 固有误差）。preference 类的 `answer` 字段是**评分 rubric 而非标准答案文本**，
不能拿来当 calibration hypothesis（首轮 6/6 校准不含该类所以没暴露）；这是校准用例构造问题，
不是评分脚本错误——正式评测用 YoAi 实际回答作 hypothesis，口径正确。

能力短板信号很清晰：多会话 20%、时间推理 40%，与审查报告“长期记忆是简单 KV、
无跨会话关联/时间索引”的判断吻合。

## 复现命令

```bash
cd $YOAI_ROOT
export PYTHONPATH="src;$YAI_CORE_SRC;$YOAI_ROOT"   # Windows 用分号分隔
python bench/run_longmemeval.py --limit 500 --seed 20261121 --out bench_results/lme-oracle-full500-v2
python bench/score_longmemeval.py --hyp bench_results/lme-oracle-full500-v2/hypotheses.jsonl \
    --out bench_results/lme-oracle-full500-v2
```

产出：`config.json`（配置快照）、`hypotheses.jsonl`（官方格式）、`traces.jsonl`（执行轨迹）、
`score.json`（分数）、`score_log.jsonl`（逐题判定）。
历史成绩保留供对比：`lme-oracle-final/`（修复前 66.67%）、`lme-oracle-fixed/`（60 题修复后 71.67%）。
全量运行耗时：答题约 17.5 分钟，评分约 13.5 分钟。

## 根因修复：生产适配器（2026-11-21 第三轮）

项目所有者（你）澄清"Core 允许合理改动"后重新审视根因——**结论是 Core 不需要改，改在适配器层**：

- **Core 的伪工具调用 fail-closed 是正确安全机制**（`protocol.py:12`、`react.py:167-186`）：
  模型把 `<tool_call>` 写进正文时既不能当答案展示、也不能解析执行。弱化它等于给假调用开后门，
  不动。路由的 direct/react/plan 与工具注入也符合设计。
- **真正的生产 bug 在 `SuanliAdapter._extract_text`**：deepseek 思考模型把 `content` 留成 None、
  答案写进 `reasoning_content`，旧代码只取 content → 判"网关返回空文本"，白丢一轮。
  已修：**content 为空时降级取 reasoning_content，有 content 绝不取思考过程**（避免把思考当答案）。
  回归测试 `test_suanli_extract_falls_back_to_reasoning_when_content_empty` +
  `test_suanli_extract_prefers_content_over_reasoning`；全量 162 passed。
- **role 结构拼串是 bench 适配器自己引入的**（生产 `GatewayModelProvider` 工具模式透传 messages，
  不存在此问题），已在 bench 侧修，不涉及生产/Corer。

这次修复的直接收益：桌面端用算里 deepseek 不再因空 content 白丢轮次。

## 记忆层改造（2026-11-21 · YoAi 内覆盖层，不动原 Core）

### 根因分析
逐题看 temporal 失败案例，发现**首因是评测输入适配缺失，不是 YoAi 记忆能力**：
`question_date`（"现在"）从未传给模型，只灌了 `haystack_dates`，模型无法算"三周前"。
A/B 验证：注入 `[当前日期：question_date]` 后，temporal 133 题 **37.6% → 52.6%（+15pp）**。

同时确认一个重要区分：**LongMemEval oracle 是长上下文 QA，YoAi 记忆层根本没被调用**。
改记忆层不会改变 oracle 分数；要验证记忆层必须用 retrieval 设置（逐条喂→记住→检索）。

### B：YoAi 时间记忆层（已实现）
新增 `src/yoai/temporal_memory.py`（**YoAi 内覆盖层，未改原 Core 项目**）：
- 事实带 `event_time`（发生时间）与 `recorded_at`（记录时间）分离——旧 PersonalContext 只记 now()；
- `events_between(start,end)` 时间范围检索、`facts_by_tag(tag)` 主题聚合（跨会话汇总）、`timeline()`；
- 原子写 + 损坏隔离，沿用既有约定；event_time 缺省回退 recorded_at，向后兼容。
`YoAiAgent` 默认启用（可 `temporal_memory=False` 关闭），`PersonalCapabilities` 新增 3 个工具：
`remember_event` / `events_between` / `facts_by_tag`。工具集 6→9。
6 项单测通过；全量 168 passed。真模型工具链实测：自己调 `remember_event` 记事件、
再调 `events_between` 查时间范围并正确回答——记忆层真实工作。

### retrieval 评测原型（已验证收益）
新增 `bench/run_longmemeval_retrieval.py`：把 haystack 逐 turn 写入 TemporalMemory
（确定性，不调模型），答题时让模型用记忆工具检索。修了两个适配问题：
日期从 `2023/02/14 (Tue) 12:45` 规范化为 ISO（否则 `events_between` 字符串比较查不到）、
用户话截取事实陈述去掉提问噪音。

**同题严格对比（temporal-reasoning 30 题，相同 question_id）**：

| 模式 | 成绩 |
|---|---|
| oracle 长上下文（无 question_date） | 14/30 = 46.7% |
| oracle + question_date 注入 | （见全量 v2 结果） |
| **retrieval 记忆层（YoAi TemporalMemory）** | **22/30 = 73.3%（+26.7pp）** |

**结论**：YoAi 用时间记忆工具检索答题，显著强于把历史一次性塞给模型。这是记忆层改造的真实收益证据。

**诚实边界**：retrieval 的记忆写入阶段是**确定性脚本**直接调 `remember_event`（不经过模型提取），
真实产品里若由模型自己决定记什么，准确率可能低于此值；且样本仅 30 题。此结果证明"记忆层有收益"，
不等于"产品已达到 73.3%"。

### 关联索引：multi-session 35.3% → 51.9%（全量 133 题）

失败案例根因：答案散落在多个 session，模型只找到一部分就下结论
（珠宝题只找到耳环漏了项链/戒指；露营只算 5 天漏了 3 天）。单纯按粗 tag 分组不够。

实现（`TemporalMemory` 内，**YoAi 覆盖层，未改原 Core**）：
- `remember_event` 加 `topics` 细粒度主题标签；
- `related_events(topic)` / `summarize_theme(topic)` / `all_topics()`：
  让模型一次查到某主题下跨会话的全部事件并求和；
- `capabilities` 暴露 4 个新工具（工具集 9→13），答题提示引导"先 all_topics 再 summarize_theme"。
- 4 项关联测试通过；全量 **172 passed**。

**结果**：multi-session 全量 133 题，oracle 基线 35.3% → retrieval+关联索引 **51.9%（+16.6pp）**。

**模型自记路径（真实产品）的实测发现 —— 关键短板**：

同 15 题严格对比（multi-session）：

| 模式 | 成绩 |
|---|---|
| oracle 长上下文基线 | 6/15 = 40.0% |
| script 记忆 + 关联索引 | 7/15 = 46.7% |
| **model 自记 + 关联索引**（真实产品路径） | **6/15 = 40.0%（无收益）** |

原因：15 题里 **6 题模型记了 0 条记忆**（`events_recorded=0`）——它常**擅自改用
`remember_fact` 而非 `remember_event`**，或对长对话判断"无事实可记"，导致时间记忆为空。
限制记忆阶段只暴露 `remember_event` 后部分题能记住（7-12 条），但仍有 40% 题失败。

**结论**：关联索引本身有效（script 模式全量 +16.6pp），但"模型自记"不稳定是当前最大短板——
记忆写入阶段必须做产品侧保障（专用提示/工具约束/确定性写入兜底），不能假设模型会严格按指令记。
这是下一步最该解决的问题，否则记忆层的收益在真实使用中会流失。

### 记忆写入保障：确定性兜底（已实现并验证）

根因诊断：模型自记失败时，`final_text` 是**英文思考过程泄漏**（"The user asks to record
specific facts..."），**一个工具都没调**就 DONE 了——不是"判断无事实"，是思考模型把
reasoning 当答案输出、没走到工具调用环节。

产品侧修复（`TemporalMemory.remember_from_transcript`，**YoAi 内，未改原 Core**）：
- 模型自记优先：模型调了 `remember_event` 就用模型的记录；
- 确定性兜底：模型 0 条调用时，从对话里规则抽取用户事实（去请求、保留陈述、打主题标签）写入；
- 保证"对话里的事实不丢"，不依赖模型自愿调工具。

**验证（同 15 题 multi-session）**：

| 模式 | 成绩 | 记0条 |
|---|---|---|
| oracle 基线 | 40.0% | — |
| model 自记（修复前） | 40.0% | **6/15** |
| **model 自记 + 兜底（修复后）** | **53.3%（+13.3pp）** | **0/15** |

来源分布：10 题模型自记 + 5 题兜底。**记忆为空归零，收益兑现**——修复后成绩超过 script 模式（46.7%）。
全量 173 passed。

**兜底的权衡**：模型自记平均 8 条/题（精炼），兜底平均 23 条/题（全量用户话，噪音大）。
兜底保证了"不丢事实"，但检索精度略降——这是"宁可多记不可漏记"的合理取舍，
后续可在兜底里加更细的事实过滤来改善。

### Retrieval 全量 500 题（记忆系统完整模式）

用"模型自记 + 兜底 + 关联索引"跑完 oracle 全量 500 题，与 oracle 长上下文模式对比：

| 题型 | oracle | retrieval | 差 |
|---|---|---|---|
| multi-session | 35.3% | **61.7%** | **+26.3pp** |
| temporal-reasoning | 54.9% | **76.7%** | **+21.8pp** |
| single-session-preference | 93.3% | 93.3% | 0 |
| single-session-user | 100% | 97.1% | -2.9pp |
| knowledge-update | 92.3% | 67.9% | **-24.4pp** |
| single-session-assistant | 98.2% | 30.4% | **-67.8pp** |
| **总分** | **69.0%** | **70.0%** | +1.0pp |

**结论（关键）**：
- **记忆层在它该管的题型上收益巨大**：跨会话 +26.3pp、时间推理 +21.8pp，
  证明 YoAi 的记忆系统（关联索引 + 时间锚点）真实有效。
- **assistant / knowledge-update 暴跌是评测适配取舍，不是记忆能力退步**：retrieval 的记忆
  写入阶段**只记用户说的话、过滤了助手回复**，而这两类题问的正是"助手之前提到的资源/结论"，
  答案根本没进记忆。oracle 模式把全部历史喂给模型，所以这两类接近满分。
- **总分持平（69→70）是因为长短互补**，不能说"记忆让总分提升"——要看分题型。
- 成本：retrieval 704 万 tokens（均 14,078/题），是 oracle（230 万）的 **3 倍**——
  工具循环多。生产使用要权衡成本。

**产品含义**：YoAi 记忆层对"记住用户的事"很强，但**没有记"助手自己说过什么"**。
若要完整，需要把助手的关键结论也纳入记忆（当前设计刻意只记用户事实）。这是下一步可选项。

产物：`bench_results/lme-retrieval-full500/`（config/progress/hypotheses/traces/score/score_log）。
全量运行：答题约 2 小时（中途断网，靠断点续跑完成）+ 评分 6.7 分钟。记忆来源：402 题模型自记 + 98 题兜底，记 0 条归零。

### 补记助手回复的实验：有得有失，总分反降（v2）

针对 assistant/knowledge 失分，做了"助手话也纳入记忆"的改造
（`remember_event` 加 speaker、`remember_from_transcript` 抽取助手事实句、模型提示覆盖助手结论），
全量 500 题重跑（`bench_results/lme-retrieval-full500-v2/`）：

| 题型 | v1 只记用户 | v2 含助手 | 变化 |
|---|---|---|---|
| assistant | 30.4% | **50.0%** | **+19.6pp** ✓ |
| preference | 93.3% | 96.7% | +3.4pp |
| knowledge-update | 67.9% | 65.4% | -2.5pp |
| temporal | 76.7% | 72.9% | -3.8pp |
| user | 97.1% | 97.1% | 0 |
| multi-session | 61.7% | **47.4%** | **-14.3pp** ✗ |
| **总分** | **70.0%** | **67.2%** | **-2.8pp** |

**诊断**：v1 对→v2 错的 multi 题有 27 道，失败原因是"记忆里没有那个数字"
（FreshMart 折扣、咖啡杯单价等）——**模型自记时注意力被助手话分散，漏记了用户的关键事实**。
这与之前"记 0 条"是同类问题：模型自记的召回不稳定。

**结论（诚实）**：补记助手话拿回了 assistant（+19.6pp），但牺牲了 multi-session（-14.3pp），
总分净降 2.8pp。**不是净收益，不采纳为默认**。两个版本都保留：
- `lme-retrieval-full500/`（v1，70.0%，只记用户）— 推荐默认
- `lme-retrieval-full500-v2/`（v2，67.2%，含助手）— 需要 assistant 类能力时可选

**真正该做的**：不是"用户/助手二选一"，而是让记忆写入阶段分别处理两类事实且不互相挤占
（例如分两次专门的抽取调用，或确定性兜底为主、模型只做补充）。这是后续方向。

### 分段式记忆实验（staged）：部分缓解，未两全

按上面方向实现了 `--memory-mode staged`：两次独立模型调用，第一次只记用户事实、
第二次只记助手结论，各有确定性兜底。同 30 题严格对比（seed 20261121）：

| 同 30 题 | v1 只用户 | v2 混合 | staged 分段 |
|---|---|---|---|
| single-session-assistant | 36.7% | 53.3% | **56.7%** ✓ 最好 |
| multi-session | **60.0%** | 50.0% | 53.3% ✗ 仍低于 v1 |

**结论**：分段式确实缓解了挤占——assistant 拿回最多（56.7%，超过混合的 53.3%），
multi 也比混合好 3.3pp。但 multi 仍低于只记用户的 v1（53.3% vs 60.0%），**没有两全**。

**为什么没完全解决**：分段只消除了"输出目标冲突"（一次要记两类），
但**用户阶段仍要读包含助手话的整段对话**，助手话依旧占用提取注意力。
失败案例："四段公路旅行的里程没记到"（记忆里没那个数字）、"课程记录被错标主题"。
要彻底解决，用户阶段应只喂用户话（不喂助手话），让输入也隔离——这是下一步。

样本仅 30 题、CI 较宽（±9pp），assistant +3.3pp / multi -6.7pp 的差异未必显著。
全量 180 passed。产物 `bench_results/staged-asst-30/`、`bench_results/staged-multi-30/`。

### 输入隔离版 staged：假设被否证

针对"用户阶段仍被助手话干扰"的判断，实现了输入隔离——用户阶段只喂用户话、
助手阶段只喂助手话。同 30 题四模式对比：

| 同 30 题 | assistant | multi-session |
|---|---|---|
| v1 只记用户 | 36.7% | **60.0%** |
| v2 一次记两类 | 53.3% | 50.0% |
| staged 分段（输入不隔离） | **56.7%** | 53.3% |
| staged 分段 + 输入隔离 | 50.0% | 53.3% |

**输入隔离无效，assistant 还退步 6.7pp**。原因：助手阶段只看助手话时，失去了用户提问的
上下文（不知道用户在问什么品牌/场景），记了一堆无针对性的结论；用户阶段本来就主要靠用户话，
喂不喂助手话影响不大。

**最终结论（重要）**：**没有任何方案能两全**。assistant 与 multi-session 存在真实的此消彼长——
根子是模型单次自记的提取容量有限，切分方式（一次/两次/输入隔离）只是在两类之间重新分配
有限的提取预算，不能凭空增加。四模式对比里 multi 的最高值始终是 v1 只记用户（60%），
assistant 的最高值始终是分段（56.7%）。**推荐配置**：默认用 v1（只记用户，总分 70.0%），
assistant 类需求强的场景可切到 staged（输入不隔离版）。全部产物保留。

## 后续实验索引（本文是主日志，记到 2026-11-22 中段；以下实验另立文档）

本文记录了 oracle 基线、记忆层改造、助手话/分段式实验。**之后的实验在各专文中**，
按时间顺序：

| # | 实验 | 文档 | 结论 |
|---|---|---|---|
| 1 | 进化机制 6 层缺口审查 | `EVOLUTION-GAP-ANALYSIS.md` | 骨架完整但三处未接线 |
| 2 | 进化机制接线（白名单/retrieval/父子） | `EVOLUTION-WIRING.md` | 技术打通但 D<A，价值未证实；**暂停不关闭** |
| 3 | 输入隔离分段式（本文末尾） | 本文 §输入隔离 | 假设否证，assistant 反退 |
| 4 | 借鉴 AMBRACE 数字正则补充 | `MEMORY-WRITE-IMPROVEMENT.md` | 全量 p=1.0 不显著，不设默认 |
| 5 | **模型自记稳定性（低温 0.1）** | `SELF-MEMORY-STABILITY.md` | **+8.8pp，p=0.000054，当前最优** |
| 6 | 低温重验进化 | `EVOLUTION-WIRING.md` §低温重验 | 假设否证，D 仍<A |
| 7 | assistant 弱项攻坚 | `ASSISTANT-WEAKNESS.md` | 三次尝试全失败，需专门立项 |

**最终权威成绩与全景见 `FINAL-SUMMARY.md`**（当前最优 retrieval 71.8%）。

> 注：本文中的测试数（173/180 passed）是当时历史记录；最终为 **187 passed**。
> 本文中的"推荐默认 v1 70%"是当时的判断——公共代码后续多次改动，
> 70% 已不可复用为对照，当前权威是同代码 A/B 的 63.0% vs 71.8%。
