# 项目台账一 · 状态（当前是什么）

> 2026-11-23 建立。只记录当前事实，不写计划（待办见 `PROJECT-LEDGER-PLAN.md`）。

## 当前快照（2026-11-27 19:00）

- **成绩**：权威仍为单轮递增+不截断+全量 500 题 **87.2%（436/500）**，CI 84.0–89.8%；评测口径未随产品扩展改变。
- **桌面**：Tauri 2 是唯一入口，Python runtime 走 IPC v1；消息动作/附件/项目模式/右侧三格工具面板已落地。全量 **420 passed + 3 skipped**，前端 **41 passed**（定时任务页 8 项 + 中断横幅 5 项），exe 已重打包（sha256 `35501023…`）。
- **RSI**：R0 反馈信号 → R1 边界看板 → R2.1 shadow 触发 → R2.2 child/parent 隔离验证 → R3.1/3.2/3.3 晋升·试用·回滚 → R4 元策略 → **R5 远端 CT 回执** 全链落地；improved 只进 probation，probation→active 必须人工批准，retired 为终态；**真实数据收益仍在观察期**。
- **扩展体系**：MCP 支持 stdio/Streamable HTTP/GET SSE 与管理页；Skill 支持脚本包/资源包/强制白名单/requirements+lockfile/本地与远程市场/自动 venv 依赖/RSI candidate/签名链/远端 CT。所有扩展工具走 Core 权限审批。
- **安全边界**：自动触发默认关；R4 元策略只改阈值权重不改安全边界；远端 CT 公钥只信 catalog；`ct_anchor` 显式调用，不自动提交公网；签名/依赖安装隔离，失败拒绝安装。
- **定时任务**：S1/S1.1/S2 已由 PR #1 合并（`67542be`）；S3 对话工具与 S4 前端页已由 PR #2 合并（`9ce38bc`），`schedule_create` 真模型弹窗并落盘任务、`schedule_list` 免弹窗正确列出。S5（共享记忆覆盖修复、目标事件、中断提示、每次运行新上下文、定时运行证据）代码完成并通过本机全量/前端测试，待推分支。默认关闭，`YOAI_SCHEDULER=1` 开启。
- **GUI 验证**：R5 技能页 20:37 目视确认通过——CT 状态、包 sha256/回执指纹、校验/锚定按钮与本地透明日志展示正常；无代码改动。
- **下一步**：见 `PROJECT-LEDGER-PLAN.md`；推 S5 分支并做 GUI 目视，RSI 真实数据继续观察。

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
| **工具热加载(2026-11-24)** | 旧会话不重启也能用上新工具：refresh_tools() diff 补缺 + `data_dir/plugins/*.py` 插件每轮 astream 前按 mtime 热加载（坏插件跳过、不许覆盖内置工具、删除类照走审批）；桌面端插件目录 `output/sessions/shared/plugins/`；8 项新测试，全量 **257 passed** | TOOL-HOTLOAD.md |
| **终端/浏览器(2026-11-24)** | `shell_run` 受限终端（无 shell 解释/cwd 限 workspace/超时/截断/剔除凭据环境变量/**不进 auto 白名单走审批**）+ `open_url` 系统浏览器（仅 http/https，auto 档）；内置 QWebEngine 面板未做（UI 编辑中+exe 增重）；9 项测试，全量 **266 passed** | TERMINAL-AND-BROWSER.md |
| **Markdown渲染(2026-11-24)** | 根因=消息整体转义后直接塞 HTML、少了"转义后解析 md"；新增 markdown_html.py（先 escape 再解析，代码块/标题/列表/链接白名单，纯标准库）；assistant/peer 消息渲染、用户输入仍纯文本；10 项测试，全量 **276 passed** | MARKDOWN-RENDERING.md |
| **过程/thinking可见(2026-11-24)** | 正文过程块：运行时展开 thinking+工序，DONE 后折叠成摘要（可点击回看）；thinking 由 YoAi 包装层拦截 raw_content_blocks 成自定义事件（**内核零改动**，跟随上游）；表格语法补齐；全量 **281 passed** | PROCESS-AND-THINKING-UI.md |
| **真·流式输出(2026-11-24)** | 每轮模型输出逐字可见：provider 用 SDK stream=True（复用 Core 公开函数组装请求/parse_response，内核零改动）；agent 起 poller 并发 drain 增量成 delta 事件（20ms 轮询、不取消 Core task）；UI 每轮独立缓冲、DONE 定稿折叠；YOAI_STREAM=0 可关；真实网关单轮+两轮工具流式冒烟通过，全量 **283 passed** | STREAMING-OUTPUT.md |
| **桌面exe流式修复(2026-11-24)** | 根因：桌面走 SuanliAdapter(讯飞 spark-x2.6)→GatewayModelProvider，第一版流式只在 Anthropic 路径、exe 未使用；修：Suanli 加 OpenAI 兼容 SSE（content/reasoning_content 增量、tool_calls 聚合），agent drain 穿透 .base+.adapter 包装链；真实网关 text/thinking 增量验证通过；**22:24 重打包 exe(57.6MB)自检通过**（22:07 首版曾有 reasoning 逐 token 裂成多行的显示 bug，已修为合并成一段）；全量 **286 passed** | STREAMING-OUTPUT.md |
| **思考默认折叠(2026-11-24)** | 用户拍板：思考内容默认折叠，只留「▸ 查看思考过程（N字）」入口；独立锚点 yoai:think:N 与过程块折叠互不干扰；已展开时一段连续文本+收起入口；22:38 exe 重打包自检通过 | STREAMING-OUTPUT.md |
| **过程行同行(2026-11-24)** | 截图反馈 [步骤] 标签与内容分行：md_to_html 段落块级 `<p>` 所致；加 inline=True（span）供过程行用，默认行为不变；**22:57 exe 重打包自检通过**，全量 **288 passed** | MARKDOWN-RENDERING.md |
| **桌面稳定态(2026-11-25 16:05)** | Tauri 新端为唯一默认（`dist/YoAi.exe` 9.9MB，回退稳定版）；原生浮窗 5 轮尝试全白屏已放弃并回退到常驻三卡侧栏；保留 60s→180s 超时修复与只读工具可发现性修复；权限三档按会话独立、按会话配置持久化；历史 thinking 落盘可见；用户旅程守护测试 7 类；本地全量 **258 passed + 1 skipped**、前端 11 passed | OLD-UI-MIGRATION.md / PERMISSION-SESSION-ISOLATION.md / DESKTOP-SWITCH.md |
| **超时口径调整(2026-11-26)** | 模型调用总时长硬上限默认取消（`model_timeout=None`，60s/180s 都误杀长推理）；卡住靠 socket 读超时、重连靠 transport_retries（流式已补重试+失败轮 outbox 回滚）；`YOAI_MODEL_TIMEOUT=<正数>` 可显式加回；全量 267 tests 0 失败 | SELF-MEMORY-STABILITY.md / STREAMING-OUTPUT.md |
| **右侧工具方格(2026-11-26)** | 现有三卡下方新增浏览器/终端/查看文件三格：iframe 内嵌+系统浏览器兜底；终端走普通任务链保留审批、展示 shell_run 的 tool_result；查看文件只读 fs.list/fs.read 锁在项目根/workspace；协议 v1 追加 3 命令+3 消息，三份 runtime 同步；全量 269 tests / 前端 20 passed / 构建通过 | TOOL-DOCK.md |
| **消息动作与附件(2026-11-26)** | 设计见 `MESSAGE-ACTIONS-DESIGN.md`：用户专有=附件/编辑/撤回，智能体专有=重新生成/停止/思考/产物，两者都有=复制/分享；附件文本抽取进上下文，撤回/编辑软删除+分支（Core 历史零改写），分享导出本地 md/html；协议 v1 追加 6 命令 3 消息 | MESSAGE-ACTIONS-DESIGN.md / IPC-PROTOCOL.md |
| **进化树研究(2026-11-26)** | 结论：骨架完整、闭环未通、价值未证（生产未调 EvolutionEngine、parent 样本为 0、两次 D<A）。已拍板补 A 闭环：生产显式开关 `YOAI_EVOLUTION=1` + 报告持久化 + 父子成对验证样本 + 星图证据链；先小样本判定 | EVOLUTION-TREE-RESEARCH.md |
| **进化树30题判定(2026-11-26)** | A 73.3%/B 76.7%/C 73.3%/D 76.7%；D vs C +3.3pp、McNemar p=1.0，不显著，**不跑全量**；父子验证样本 parent_items 从 0→28，但按标签分组仍 insufficient；judge 因网关切换改 spark-x2.6 | EVOLUTION-AB-30-RESULT.md |
| **RSI R0 反馈信号(2026-11-26)** | 编辑/撤回/重新生成/复制/分享动作全部写 `evidence/feedback.jsonl`，绑定执行证据与能力标签；协议追加 feedback.record/recorded；**只采集，不触发进化**；Python 279 tests / 前端 24 passed | RSI-PRODUCT-RESEARCH.md |
| **RSI R1 能力边界看板(2026-11-26)** | 左侧导航新增「边界」页；按能力标签展示样本数、成功率、Wilson 区间、返工率、正向信号、相对基线与状态分级；协议追加 boundary.get/state；**只统计，不触发进化**；Python 282 tests / 前端 25 passed | RSI-PRODUCT-RESEARCH.md |
| **RSI R2.1 shadow 触发(2026-11-26)** | 新增 TriggerEngine：样本≥20+weak+归因门槛+7天冷却才生成 candidate；一次只改一个能力维度；看板薄弱行可手动触发，星图显示候选与触发报告；**不进路由、不晋升**；协议追加 rsi.trigger/triggered | RSI-PRODUCT-RESEARCH.md |
| **RSI R2.2 隔离验证(2026-11-26)** | 新增 CandidateValidator + rsi.validate/validated；星图候选节点可手动验证；三类 smoke 结论 improved/regression/no_regression 均不晋升；协议/文档/台账同步 | RSI-PRODUCT-RESEARCH.md |
| **RSI R3.1 受控晋升(2026-11-26)** | R3Promoter 接 rsi.validate：improved→probation、regression→retired、其余留 candidate；样本≥5/单维度/成本≤父节点+20% 硬门槛；协议追加 rsi.promoted，星图显示结果；**绝不直接 active** | RSI-PROMOTION-PLAN.md |
| **RSI R3.2 试用与批准(2026-11-26)** | TrialStore/Controller + SAMPLE_TRIAL 隔离 + tag scope 临时路由 + 人工批准/拒绝；smoke 中 temporal probation→trial→active；协议追加 trial/approval 消息；Python 294 tests / 前端 25 passed | RSI-PROMOTION-PLAN.md |
| **RSI R3.3 shadow/回滚(2026-11-26)** | 真实任务 trial 命中时后台隔离跑 parent 并落成对的 trial 证据；active 节点每次任务后做 30 天回归监控，命中自动 retired 回退父节点；星图可手动检查回滚；协议追加 rsi.rollback/rolled_back | RSI-PROMOTION-PLAN.md |
| **MCP 标准协议(2026-11-26)** | stdio + Streamable HTTP JSON-RPC 2.0 client（initialize/tools/list/tools/call/ping、JSON/SSE 响应、session/版本头、DELETE、GET SSE 订阅/续传）；servers.json 配置热更新；桌面「MCP」管理页；外部工具注册为 Core ToolSpec(source=mcp) 走权限审批；Python 306 tests / 前端 26 passed，**未做完整 OAuth/UI 安装市场** | MCP-SUPPORT.md |
| **Skill 基础层(2026-11-26)** | skills.json 配置热更新；skill_list/load/run/resource_read 四个元工具；脚本包（无 shell/白名单环境/超时）+ 资源包（声明路径隔离）+ enforce_tools 强制白名单；requirements.txt / requirements.lock.txt；技能市场（本地 + 远程 catalog/zip/sha256/Ed25519 签名）；安装后自动建 venv 装依赖；安装后自动入 RSI 候选；桌面「技能」管理页；**未做未登记 URL 下载** | SKILL-SUPPORT.md |
| **签名链/CT/R4 元递归(2026-11-26)** | 远程 Skill 支持 root→signer Ed25519 证书链与 append-only 透明日志；安装后自动建隔离 venv 装依赖并生成 RSI candidate；R4 元策略版本化（阈值/权重），提案需人工批准，active 元策略驱动 R3Promoter/RollbackMonitor；Python 320 tests | RSI-META-RECURSION.md / SKILL-SUPPORT.md |
| **R5 远端 CT 回执(2026-11-26)** | RemoteCtClient 验证 catalog 提供的 ct_public_key 签发的回执（Ed25519 + RFC6962 风格 Merkle proof）；安装远程包前强制复验，缺公钥/回执无效即拒绝；技能页可随时复验与显式 POST /anchor，回执入本地透明日志；协议 skill.ct_verify/anchor/result；**不自动向公网提交** | SKILL-SUPPORT.md |
| **runtime 接入修复(2026-11-25 上午)** | 修复 4 个真 bug：①start_task 漏 create_task（任务从未执行）②数据目录指错（旧会话不可见）③YAI_CORE_SRC 指向 src 致网关静默降级 ④空目录首次启动 KeyError；补单实例守卫；实测 task→161 事件→final→done，dist exe 重编 9.9MB；全量 241 passed | OLD-UI-MIGRATION.md 第七节 |
| **旧端UI搬迁+清理(2026-11-25)** | PySide6 端全部能力搬入 Tauri 新端（会话管理/侧栏卡片/通讯页/星球系/纸墨主题/错误可见/模型chip/证据落盘），随后旧端源码删除（src/yoai/desktop/ 16文件+cosmic 7文件+10个Qt测试+yoai.spec）；协议 v1 追加 snapshot/chat.*/archive.*；新增 yoai/bootstrap.py 承接 agent 组装；全量 **241 passed**、前端 8 passed、Rust 构建成功、dist/YoAi.exe+runtime 已更新；dist/YoAi-PySide6.exe 留作回退 | OLD-UI-MIGRATION.md |
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
| GitHub 仓库 | https://github.com/Gi-Tuu/YoAi（公开）；master=b74379a（本地，未 push；远端 0d0d28d）；**CI 已配**（GitHub Actions，push/PR 全量 pytest；本地全量 258 passed + 1 skipped） | .github/workflows/tests.yml |
| License | PolyForm Noncommercial 1.0（限制商用） | 同系列可平滑升级商用 |
| CLA | 版权转让型 | CLA.md + CONTRIBUTING.md |
| 云端资料库 | `ASSISTANT-ROOT-CAUSE-BREAKTHROUGH` doc 为更新目标 | 已同步区间结论 |
| README/门面 | 已做脱敏整改；UI 已重做为纸墨工作台（左侧导航＋中央对话＋可收起检查器） | 197 项测试＋自渲染截图 |
| Core 内核 | 基于它做产品，**可以改但要能跟 Core 更新**；目前改动都在 YoAi 侧（继承公开类/SPI/电池注入），原 Core 文件零改动 | 项目 MEMORY.md 约定（2026-11-24 修正） |
