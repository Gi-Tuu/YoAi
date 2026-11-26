# 进化树 A/B/C/D 30 题小样本结果（evo4）

> 2026-11-26。承接 `EVOLUTION-TREE-RESEARCH.md` 与「补 A 能力进化树闭环」首轮实现。
> 目的：判定 D（指纹路由 + 专家差异）是否明显优于 C（分支但不路由）；不显著则不跑全量。

## 一、实验设置

- 数据：LongMemEval oracle 500 题，固定 seed `20261121`，每组抽 30 题。
- 记忆阶段：`--memory-mode model --memory-temperature 0.1`（已验证的低温底座）。
- 答题阶段：retrieval，模型用记忆工具检索；四组记忆逻辑相同。
- 专家差异（本轮已改）：root/memory/research 使用**同一套全量记忆工具**，差异只在
  `prompt_suffix` 与能力标签；父版本仍是弱基线（基础工具）。
- 执行：4 组 × 4 分片 = 16 进程并行；结果按分片合并，每组判分只取 child 变体。
- 判分：官方 anscheck prompt 原样保留，judge=`spark-x2.6`（当前网关可用模型；
  C/D 首轮 8 路并发触发网关限流，降为串行后重判成功）。**不可与官方榜单直接比**。
- 产物：`bench_results/evo4-30/`。

## 二、成绩

| 组 | 定义 | 正确/总数 | 准确率 | Wilson 95% CI |
|---|---|---|---|---|
| A | 固定根，无路由 | 22/30 | **73.3%** | 55.6%–85.8% |
| B | 线性单链 | 23/30 | **76.7%** | 59.1%–88.2% |
| C | 多分支但不路由 | 22/30 | **73.3%** | 55.6%–85.8% |
| D | 指纹路由 + 专家差异 | 23/30 | **76.7%** | 59.1%–88.2% |

分题型（准确率）：

| 题型 | A | B | C | D |
|---|---|---|---|---|
| multi-session | 71.4% | 71.4% | 71.4% | 71.4% |
| temporal-reasoning | 66.7% | 88.9% | 77.8% | 77.8% |
| single-session-assistant | 33.3% | 66.7% | 66.7% | 66.7% |
| knowledge-update | 100% | 66.7% | 50% | 66.7% |
| preference | 50% | 50% | 100% | 100% |
| user | 100% | 100% | 100% | 100% |

## 三、统计判定

- **D vs C：+3.3pp（23/30 vs 22/30），McNemar 修对 4 / 弄坏 3，p=1.0**。
- B vs A：同样 +3.3pp（修对 3 / 弄坏 2，p=1.0）。
- D vs A：也是 +3.3pp（修对 4 / 弄坏 3，p=1.0）。
- 四组 Wilson 区间高度重叠；**没有任何统计证据支持路由或分支结构带来收益**。

## 四、父子验证样本闭环

- D 组共生成 58 条 `sample_class=validation` 证据：30 条 child + 28 条 parent
  （2 题路由到根节点，没有可对照的父版本）。
- 相对上一轮「parent_items 恒 0」，父子成对结构已经打通：BenchmarkLab 能识别
  child/parent 并进入边界评估。
- 但按能力标签分组后每组样本仍 <3，各分片 verdict 仍为 `insufficient`。
  **这是样本量限制，不是链路断裂**；本轮不改 `min_samples` 来制造结论。

## 五、结论

1. 本轮把「专家差异 = 工具更窄」改成「同工具集 + 不同提示词」后，
   D 不再低于 A/C，但**只高 3.3pp 且 p=1.0**，属于随机波动。
2. B（线性单链）与 D 完全同分，说明当前差异配置下**路由机制本身没有可测净收益**。
3. 按预设判据（D 明显优于 C 才跑全量），**不跑 500 题全量**。
4. 诚实口径：进化机制的数据/生产/可视化闭环已补通，但产品价值仍未证实；
   下一步若要继续，应换更强的专家差异维度（工具扩展、模型档位、预算）或增加
   每个能力标签的验证样本量，而不是继续叠同一套提示词路由。

## 六、复现

```bash
python bench/run_evolution_ab.py --group A --offset 0 --limit 8 --seed 20261121 --out bench_results/evo4-30/shards/A0 --memory-mode model --memory-temperature 0.1
# 其余分片 offset=8/16/24，limit=8/8/6；组名换成 B/C/D 各跑一遍
python bench/merge_evolution_shards.py --shards bench_results/evo4-30/shards --out bench_results/evo4-30
YOAI_JUDGE_MODEL=spark-x2.6 python bench/score_longmemeval.py --hyp bench_results/evo4-30/D/hypotheses.jsonl --out bench_results/evo4-30/D --concurrency 1
```
