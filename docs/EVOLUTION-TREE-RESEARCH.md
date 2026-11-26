# 进化树研究现状（2026-11-26）

> 只读研究，不改代码。承接 `EVOLUTION-PLAN.md` / `EVOLUTION-WIRING.md` /
> `EVOLUTION-GAP-ANALYSIS.md`，回答「现在到底有什么、缺什么、下一步该研究什么」。
> 归属判断：进化树一直是 **YoAi 外层能力**，Core 零改动；后续也应保持这个边界。

## 一、结论先行

**进化树不是没做，而是「骨架完整、闭环未通、价值未证」。**

1. **M0 档案层已实现**：`EvolutionArchive` 能建根、生子、状态迁移、恢复点、证据索引，持久化在 `data_dir/evolution/evolution.json`。
2. **M1 路由层已实现**：`ExpertRouter` 按任务指纹从 active 专家里选一个，带 `RouteDecision` 审计；max_performance 模式仍是 `NotImplementedError`。
3. **M2 引擎层代码存在**：`EvolutionEngine.evolve(evidence_id)` 串起归因→候选→隔离评测→晋升决策，但**生产 runtime 从不调用它**，只有测试调用。
4. **前端星图是真实档案数据**：`GalaxyPage` 消费 `archive.state`，节点来自 `EvolutionArchive`，不是写死的演示数据；但因为生产不触发进化，树通常只有一个根节点或少量手工/实验节点。
5. **产品价值两次否证**：专家工具白名单接线后，D 组（完整进化）在 script 底座 16.7% < A 组 20.0%；低温修复写入后 66.7% < 73.3%。限制工具集是负收益，不是中性。

一句话：**进化树的「数据结构 + 可视化」已经可用，但「自己生长并证明有用」这条链没通。**

## 二、现状分层

| 层 | 代码 | 状态 | 证据 |
|---|---|---|---|
| M0 档案 | `src/yoai/evolution/{models,archive}.py` | ✅ 已实现 | 13 项离线测试；JSON 原子写、损坏隔离 |
| M1 路由 | `src/yoai/evolution/{fingerprint,router}.py` | ✅ 已实现 | 14 项测试；按标签/策略/工具覆盖打分，根节点回退 |
| M1 白名单接线 | `expert_provider.tools_for` + `YoAiAgent.tool_filter` | ✅ 技术接通 | 5 项单测；评测里两个专家确实调到不同工具集 |
| M2 候选/门控/引擎 | `candidate.py` / `promotion.py` / `engine.py` | ⚠️ 代码有，生产未接 | 12 项测试；runtime 中搜不到 `EvolutionEngine.evolve` 调用 |
| M2 评测 | `bench/run_evolution_ab.py` | ⚠️ 技术通、价值否证 | A/D 各 30 题两次，D 均低于 A |
| M3 最高性能模式 | `router.py` 中 `NotImplementedError` | ❌ 未实现 | 预算内候选低成本试跑仍是规划 |
| M4 长期指标 | 无 | ❌ 未实现 | 真实任务试用/趋势/退化告警都没做 |
| UI 星图 | `GalaxyPage.tsx` + `archive.state` | ✅ 已接真实数据 | 只展示档案；缺晋升理由/证据链/不确定性 |

## 三、真实数据流

```
任务输入
  → fingerprint() 生成任务指纹 / 能力标签
  → ExpertRouter.route() 选中 active 专家（或回退根节点）
  → ExpertModelProvider 按 spec.tools 限制工具集
  → YoAiAgent.astream() 执行，产出事件
  → runtime 落 ExecutionEvidence + Attribution（expert_id / parent_id / 指纹）
  → 到这里为止：生产链路结束
```

`EvolutionEngine.evolve()` 目前只在测试里被调用。也就是说：

- 证据在积累，但**证据不会自动推动树生长**；
- `BenchmarkLab` 要 `sample_class=validation` 且父子各 ≥3 条样本，生产只写 `sample_class=evolution`，所以 `PromotionGate` 几乎必然 `insufficient`；
- 星图上的节点主要来自测试/实验脚本，不是日常任务自然长出来的。

## 四、关键缺口（按重要性）

1. **生产闭环缺口**：任务结束后没有调用 `EvolutionEngine.evolve`，也没有显式的「触发进化」入口。
2. **验证样本缺口**：`BenchmarkLab` 用 isolation validation set，但生产没有生成父子成对验证样本；父节点 retired/不参与路由，parent_items 恒 0。
3. **价值假设缺口**：当前「专家差异化 = 工具白名单更窄」的方向已被两次否证。继续缩小工具集只会更差。
4. **可视化信息缺口**：星图有节点和血统，但没有展示「为什么晋升/为什么没晋升、证据数、Wilson 区间、父/子对照」。
5. **M3/M4 缺口**：候选试跑、预算墙、长期成功率趋势、退化告警都还没有。

## 五、要继续研究，应先选「进化树」是哪一种

| 方向 | 含义 | 当前基础 | 适合问题 |
|---|---|---|---|
| A. 能力进化树 | 当前设计：专家配置节点 + 路由 + 晋升 | 最完整 | 能不能让 YoAi 越来越会选能力 |
| B. 会话分支树 | 刚做的软删除+编辑形成版本图 | 已有数据层 | 用户改提问/撤回后的分支管理，不是能力进化 |
| C. 工具/技能进化树 | 失败任务催生新工具或插件，验证后保留 | 有热加载插件基础，无闭环 | 让 Agent 自己补能力，而非只换提示词 |

本报告默认研究 A；若要研究 B/C，应另立设计。

## 六、如果要让 A 继续，最小可信闭环建议

1. **先接生产入口**：任务结束旁路调用 `EvolutionEngine.evolve(evidence_id)`，但默认关闭，由显式开关触发，避免每次对话都长分支。
2. **重定义专家差异**：放弃「工具越少越专业」，改成同一基础工具集下的 `prompt_suffix / model_tier / budget / strategy_bias` 差异，或「工具更多 + 路由更准」的增益方向。
3. **造父子成对验证样本**：同一批验证题各跑 child/parent，`sample_class=validation`，证据带正确 `expert_id/parent_id`，让 `BenchmarkLab` 不再是 insufficient。
4. **先小样本判定**：A/B/C/D 各 30 题；只有 D 明显优于 C 才跑全量。仍然坚持「同代码单变量」。
5. **星图补证据链**：节点详情展示晋升理由、样本量、Wilson 区间、父/子对照；没有证据的节点不应看起来像「已进化成功」。

> **2026-11-26 更新**：30 题小样本已跑完，结果见 `EVOLUTION-AB-30-RESULT.md`。
> A 73.3% / B 76.7% / C 73.3% / D 76.7%，D vs C +3.3pp、McNemar p=1.0，
> **不显著，按预设判据不跑全量**。父子验证样本已从 parent_items=0 变为 28 条 parent 证据，
> 但按能力标签分组后样本仍不足，BenchLab 仍 insufficient。

## 七、下一步已拍板：补 A 能力进化树闭环

已选方向 A。首轮实施范围：

1. 生产任务结束旁路接 `EvolutionEngine.evolve`，由 `YOAI_EVOLUTION=1` 显式开启，默认关；
2. 进化报告落 `data_dir/evolution/reports.jsonl`，协议推 `evolution.report`；
3. 专家差异从「工具更窄」改为「同基础工具集 + 不同提示词」，父版本仍是弱基线；
4. 评测脚本同一批验证题分别跑 child/parent，`sample_class=validation`，证据带正确 `expert_id/parent_id`；
5. 星图节点详情展示晋升理由、样本量、Wilson 区间与父/子对照。

仍坚持：先 30 题小样本判定，D 明显优于 C 才跑全量；否则诚实写「当前设计不适用」。

## 八、诚实边界

- 不能把「M0-M2 骨架写完」说成「进化树有效」；
- 不能把两次 D<A 的结果包装成成功；
- 不应为了跑通 `BenchmarkLab` 而制造父节点假样本；
- 若下一轮小样本仍无收益，应把结论写成「当前设计不适用」，而不是继续叠机制。
