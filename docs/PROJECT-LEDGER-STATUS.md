# 项目台账一 · 状态（当前是什么）

> 2026-11-23 建立。只记录当前事实，不写计划（待办见 `PROJECT-LEDGER-PLAN.md`）。

## A. 成绩与评测

| 项 | 当前状态 | 出处 |
|---|---|---|
| 权威成绩 | **87.2%（436/500）**，Wilson CI 84.0–89.8%；**现可复现**（百炼全量复核436/500同分） | FINAL-SUMMARY.md |
| 成绩口径 | 单轮递增 + 不截断 + 全量；新代码段 88.2%（351/398），前102题旧段 83.3% | bench_results/lme-inc-500-fix/ |
| 分题型 | assistant 100%、user 98.6%、knowledge 87.2%、temporal 85.7%、preference 80%、multi 78.9% | — |
| 确定性铁证 | assistant 专项 A/B 66.7%→96.7%，修对9/弄坏0，p=0.0039 | ASSISTANT-ROOT-CAUSE-BREAKTHROUGH.md |
| 批量口径（历史） | 71.8%（500题，低温）/ 63.0% 对照；非产品真实水平 | SELF-MEMORY-STABILITY.md |
| 最新评测产物 | `bench_results/lme-bailian-500/`（当前可复现基线）、`lme-inc-500-fix/`（原始） | — |
| 网关迁移 | 算里key到期(401)→百炼同款ds；30题76.7%=76.7%，**全量436/500=436/500**，68翻转34:34对称McNemar p≈1 | MODEL-GATEWAY-CANDIDATES.md |
| 评测成本/缓存 | 全量1.13亿token(31977次调用)；缓存命中62.2%省36%；实际¥106(空闲)/¥211(高峰)，错峰是最大杠杆 | lme-bailian-500/usage_stats.json |
| 生产写入保障 | A/B/C已实施：按来源计数可观测 + 确定性兜底(opt-in) + 数字补充(opt-in)；**真实生产验证兜底接管成功**(中文事实信号bug已修) | PRODUCTION-MEMORY-WRITE-PLAN.md |
| 生产网关(2026-11-24) | 算里死key→**讯飞 spark-x2.6**(10亿token/31天)：tool_calls完美、串行12/12=100%稳定、2.4s/次；Core .env已切，备份.env.bak-20261124-010247 | 本机Core/.env |
| 生产工具集 | **18个**：12记忆/目标 + 4文件(file_list/read/create/patch) + 2联网(web_search/fetch)；文件工具用Core现成电池+gate，读全workspace/、写限白名单子目录 | PRODUCTION-TOOL-SILENT-FAILURE.md |
| 生产问题修复 | ①DIRECT静默失败→工具优先路由(YoAiRouter) ②UI错误可见 ③实操工具 ④过渡语停住→适配层re-ask；均YoAi侧不改内核 | PRODUCTION-STALL-REASK.md 等 |
| **工具扩展(2026-11-24)** | YoAi 自检反馈五项能力落地：now 时间源 / forget_fact+forget_event+recent_events 删除 / file_ro_list+file_ro_read 只读挂载(YOAI_READONLY_ROOTS) / list_tools 自省 / request_capability 接线；删除类不进 auto 白名单（弹窗）；全量 **249 passed**，CI 绿，exe 18:40 重打包自检通过 | SELF-REPORT-TOOLS-2026-11-24.md |
| 桌面exe(2026-11-24) | **18:40重新打包** `dist/YoAi.exe`(57.6MB，含工具扩展+模型迁移)，自检 SELFCHECK_OK（只读挂载默认关，设 YOAI_READONLY_ROOTS 后生效） | SELF-REPORT-TOOLS-2026-11-24.md |
| 进程/单实例 | QLocalSocket单实例守卫(进程死OS自动释放，无陈旧锁)；worker的requestInterruption真cancel asyncio任务，根治关窗后YoAi.exe残留 | src/yoai/desktop/single_instance.py |
| 权限3档 | 桌面用Core的AllowlistPolicy(auto档)：只读+记忆/目标内部写白名单自动过，文件写弹窗确认(默认拒绝/关窗一律拒绝)；Core默认CollectChannel.confirm永远True已替换；YOAI_PERMISSION_MODE=allow_all可切全放行(默认auto) | src/yoai/desktop/approval.py |
| 500题全量 | **已完成**（2026-11-23，免费额度最后一天） | — |
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
| 全量测试 | **240 passed**, 50 warnings | 2026-11-24 16:40 实跑 |
| Anthropic路径 | 多tool_result合并到一条user消息，根治HTTP400 tool_use无result(生产复现)；thinking块回传已由Core官方实现接管 | ANTHROPIC-TOOL-RESULT-400.md |
| **模型迁移(2026-11-24)** | 主对话 DeepSeek Anthropic 网关路径 → **Core 官方 AnthropicProvider**（YoAi 包装层保留异常降级+stall 重试）；peer 聊天仍走旧 adapter；prompt_cache 默认关；真实网关两轮工具循环验证无 400 | MODEL-MIGRATION-CORE-ANTHROPIC.md |
| Core thinking 分支 | d4a2204 已合并进 Core main 并 **push origin**（Gitee dd07fb4..d4a2204）；Core 相关测试 63 passed | MODEL-MIGRATION-CORE-ANTHROPIC.md |

## C. 工程与对外

| 项 | 当前状态 | 备注 |
|---|---|---|
| GitHub 仓库 | https://github.com/Gi-Tuu/YoAi（公开）；master=0d0d28d；**CI 已配**（GitHub Actions，push/PR 全量 pytest，240 passed 绿） | .github/workflows/tests.yml |
| License | PolyForm Noncommercial 1.0（限制商用） | 同系列可平滑升级商用 |
| CLA | 版权转让型 | CLA.md + CONTRIBUTING.md |
| 云端资料库 | `ASSISTANT-ROOT-CAUSE-BREAKTHROUGH` doc 为更新目标 | 已同步区间结论 |
| README/门面 | 已做脱敏整改；UI 已重做为纸墨工作台（左侧导航＋中央对话＋可收起检查器） | 197 项测试＋自渲染截图 |
| Core 内核 | 基于它做产品，**可以改但要能跟 Core 更新**；目前改动都在 YoAi 侧（继承公开类/SPI/电池注入），原 Core 文件零改动 | 项目 MEMORY.md 约定（2026-11-24 修正） |
