# 项目台账一 · 状态（当前是什么）

> 2026-11-23 建立。只记录当前事实，不写计划（待办见 `PROJECT-LEDGER-PLAN.md`）。

## A. 成绩与评测

| 项 | 当前状态 | 出处 |
|---|---|---|
| 权威成绩 | **82%–94% 区间**（100题，中位约88%） | FINAL-SUMMARY.md |
| 成绩口径 | 单轮递增写入 + 不截断（真实生产形态）；同配置两次运行 94%/82%，波动 ±12pp | INCREMENTAL-EVAL-PROTOCOL.md |
| 确定性铁证 | assistant 专项 A/B 66.7%→96.7%，修对9/弄坏0，p=0.0039 | ASSISTANT-ROOT-CAUSE-BREAKTHROUGH.md |
| 批量口径（历史） | 71.8%（500题，低温）/ 63.0% 对照；非产品真实水平 | SELF-MEMORY-STABILITY.md |
| 最新评测产物 | `bench_results/lme-inc-100-fix/`（94%）、`lme-inc-500-fix/` 前100题（82%） | — |
| 500题全量 | 未跑完（停在约100题） | — |
| 评测提速 | **已完成**：题内并发8路(3.8-6.7×)+judge并发8路(6×)，500题17h→2.5-4.5h，等价性验证通过 | BENCH-SPEED-OPTIMIZATION-PLAN.md |

## B. 技术状态

| 项 | 当前状态 | 备注 |
|---|---|---|
| 时间记忆层 | `temporal_memory.py`，生产默认启用（可关） | YoAi 内覆盖层，原 Core 零改动 |
| 记忆写入 | 生产 = 主对话顺带调 remember_event；单轮低温抽取已验证可行，未接生产 | SINGLE-TURN-MEMORY-FEASIBILITY.md |
| 生产温度 | 未改（单轮验证无需调温） | — |
| 截断 bug | 已修（`--max-chars 0` 设默认） | 根因级修复 |
| judge 环境 | env 回退 bug 已修（加 Core 目录回退） | score_longmemeval.py |
| 进化机制 | 接线完成，价值未证实，暂停 | EVOLUTION-WIRING.md |
| assistant 弱项 | 根因（截断）已修，专项 96.7%；剩余波动来自自记随机性 | — |
| 全量测试 | 187 passed, 39 warnings | — |

## C. 工程与对外

| 项 | 当前状态 | 备注 |
|---|---|---|
| GitHub 仓库 | https://github.com/Gi-Tuu/YoAi（公开，已推送） | 最新提交见 `git log` |
| License | PolyForm Noncommercial 1.0（限制商用） | 同系列可平滑升级商用 |
| CLA | 版权转让型 | CLA.md + CONTRIBUTING.md |
| 云端资料库 | `ASSISTANT-ROOT-CAUSE-BREAKTHROUGH` doc 为更新目标 | 已同步区间结论 |
| README/门面 | 已做脱敏整改，UI 待美化 | — |
| 原 Core 项目 | 只读引用，零改动 | — |
