# 进化机制接线项目 · EVOLUTION-WIRING

> 立项：2026-11-22。承接 `EVOLUTION-GAP-ANALYSIS.md` 的 6 层缺口审查。
> 目标：把"专家能力"从纸面配置变成真实执行差异，让 A/B/C/D 对照能测出路由净收益。
> 约束：**所有改动在 YoAi 内**（`src/yoai/`、`bench/`），原 Core 项目只读引用、零改动。

## 一、三处接线 + 一处评测改造

### 接线 1：专家工具白名单真正生效（根）
**问题**：`ExpertSpec.tools` 只用于路由打分（`router.py:148`），执行时从不按它过滤工具。
**方案**：
- `ExpertModelProvider` 新增 `tools_for(task)`：先 `router.route(task)`，返回选中节点
  `spec.tools`；空集表示"不限制"（保持向后兼容，root 用空集=全部工具）。
- `YoAiAgent` 新增可选 `tool_filter: Callable[[str], set[str] | None]`，在 `astream(task)`
  开始时调用，按返回的白名单**就地重建** `core.registry._tools`（loop 与 core 共享同一对象，
  不能替换引用）。传 None 表示不启用过滤。
- 默认不启用（生产行为不变）；评测适配器显式接入。

### 接线 2：评测切 retrieval 模式
**问题**：oracle 把全部历史喂给模型，工具查历史无意义，测不出工具差异。
**方案**：进化评测改为 retrieval 设置——
- 记忆阶段：haystack 用户话确定性写入 `TemporalMemory`（带时间/主题）；
- 答题阶段：模型按专家白名单用记忆工具检索回答（带工具的专家应显著更强）。

### 接线 3：父子成对验证样本
**问题**：`BenchmarkLab._boundary` 要求每个 tag 边界 node 与 parent 各 ≥3 条样本，
旧链路 parent_items 恒 0 → 永远 insufficient。
**方案**：每个专家建一个"父版本"（工具更少的弱配置），parent/child 各自跑同一批验证题，
证据 `parent_id` 指向父节点，让 lab 能成对评测。

### 评测改造：四组配置用真实工具差异
| 组 | 配置 | 预期 |
|---|---|---|
| A 固定 Agent | 单一 root（全部工具），无路由 | 基线 |
| B 线性自进化 | 单链，只留最新节点（全部工具） | 测灾难性遗忘 |
| C 分支但不路由 | 多节点都在，固定选 root | 分支本身无收益 |
| D 完整机制 | 指纹路由，专家带**不同工具白名单** | 路由净收益 |

**关键**：D 组的差异来自"专家工具白名单不同"——这是真实能力差异，不是提示词换皮。

## 二、验收标准

1. **接线 1**：单测证明"白名单生效"——设白名单后 `agent.list_tools()` 只剩白名单工具，
   且模型实际调用被限制；不设时行为完全不变（向后兼容）。
2. **接线 2**：评测确实走工具检索（traces 里有 TOOL_CALL）。
3. **接线 3**：`BenchmarkLab.evaluate(child_id, parent_id)` 不再是 insufficient
   （父子样本各 ≥3）。
4. **四组对照**：D vs C 有可测差异（若仍完全持平，则诚实报告"路由无净收益"）。

## 三、诚实风险

- 若"带工具专家 vs 裸答"在小样本上无差异，说明当前任务集下工具也不产生收益，
  应诚实报告并停止，不堆全量。
- 父子成对会让样本量翻倍，但额度无限，可接受。
- 全程 judge 是 deepseek 非官方 gpt-4o，不可与榜单直接比（口径一致）。

## 四、实施记录（2026-11-22）

### 接线 1 完成 ✓
- `ExpertModelProvider.tools_for(task)`：路由后返回选中节点 `spec.tools`（空=不限制）。
- `YoAiAgent` 加 `tool_filter` 参数，`astream` 开始时**就地重建** `registry._tools`
  （保持 core/loop 共享引用不变，不替换对象）。
- 5 项单测通过：白名单生效 / None=全部 / 不同任务切换 / loop 引用一致 / 向后兼容。
- 全量 185 passed。

### 接线 2+3 + 评测改造完成 ✓
- `bench/run_evolution_ab.py` 重写为接线版（retrieval + 父子成对 + 白名单）。
- 冒烟 D 组 3 题验证：两个专家调的工具集确实不同
  - research_expert: all_topics/list_facts/summarize_theme/related_events
  - memory_expert: events_between/all_topics/list_facts/facts_by_tag
  - parent_id 成对结构生效；BenchmarkLab 能按 child/parent 配对（样本量不足时仍 insufficient，属正常）。

### 小样本验证结果（2026-11-22）—— 技术成功，产品价值未证实

**接线技术全部成功**：
- 白名单生效 ✓：research_expert 只调 AGGREGATE_TOOLS、memory_expert 只调 TIME_TOOLS，工具集确实不同；
- retrieval ✓：模型真实调用记忆工具检索；
- 父子结构 ✓：证据带 expert_id + parent_id，BenchmarkLab 能识别配对。

**但产品价值未证实（诚实）**：
| 组 | 30 题成绩 |
|---|---|
| A 固定 Agent（全工具） | 20.0% (6/30) |
| D 完整进化（专家工具白名单） | **16.7% (5/30)** |

**D 比 A 还差 3.3pp**。原因：限制工具集没带来收益，而 retrieval 的记忆写入质量差
（每题只记 11-12 条、关键数字漏记）是更根本的瓶颈——工具再精准也查不到没记进去的事实。
这与之前记忆层实验的结论一致：**瓶颈在记忆写入，不在检索工具**。

**接线 3 未完成闭环**：30 题证据里只有 child 节点跑过（23/7 条），
父节点被设 retired 不参与路由、从未执行，所以每个 tag 边界的 parent 样本为 0，
BenchmarkLab 仍 insufficient。要闭环需让同一批题各跑两遍（child + parent），
但既然 D 已经比 A 差，跑出 verdict 也只会是 regression，无意义。

**最终判断**：进化机制的三处接线在技术上全部打通并可测（这是真实交付），
但**当前记忆写入质量下，进化路由没有净收益，甚至略负**。不跑全量制造假数据。
真正该做的是先把记忆写入质量提上去（这是另一条线），再回来验证进化价值。

产物：`bench_results/evo2-check/`（A/D 30 题）、`bench_results/evo2-smoke/`（D 3 题冒烟）。

### 低温底座重验（2026-11-22 续）—— 假设否证

低温修复自记稳定性后（retrieval +8.8pp），回头重验"进化无收益是否因写入质量差"。
改造 `run_evolution_ab.py` 支持 `--memory-mode model --memory-temperature 0.1`
（记忆阶段走低温模型自记，四组一致；答题工具白名单差异不变）。

同 30 题（seed 20261121）结果：

| 组 | script 底座（旧） | **低温底座** |
|---|---|---|
| A 固定全工具 | 20.0% | **73.3%** |
| D 完整进化（专家白名单） | 16.7% | **66.7%** |

- 低温把整体抬高（A 20%→73.3%），但 **D 仍比 A 差 6.6pp**——限制工具集依然是负收益。
- 诊断：D 组失败题里专家拿到 `events_between/facts_by_tag` 等时间工具，
  但"记忆里没有那条记录"——问题在检索不到，不在路由错。且 3 个失败题路由到同一个专家，
  白名单成了限制而非增益。
- **结论（诚实）**：即使写入质量修复，进化路由在当前设计下仍无净收益。假设否证，
  不跑全量（小样本已显示 D<A 且机制原因清楚）。进化这条线**暂停，待后续研究**（用户明确要求不关闭）。

产物：`bench_results/evo3-lowtemp/`（A/D 各 30 题低温底座）。

## 五、排期（全部已完成/已定性）

1. ~~接线 1 + 单测~~ ✓（白名单生效、loop 引用一致）
2. ~~接线 2 + 3 + 评测适配器改造~~ ✓（retrieval + 父子结构）
3. ~~小样本验证~~ ✓（白名单生效 ✓ / 工具差异 ✓ / lab 成对结构 ✓ 但 parent 未执行→样本不足）
4. ~~四组对照~~ — 小样本已两次证明 D<A（script 底座 16.7%<20%、低温底座 66.7%<73.3%），
   价值未证实，**跑全量无意义，未跑**。进化线**暂停待后续研究**（用户明确不关闭）。
