# YoAi — 个人自主智能体

基于 [YAI Agent Core](../../Competition/YAI%20Agent%20Core) 构建的开源个人智能体。
Core 是嵌入式自适应内核（规划 / 工具 / 治理 / 事件流），YoAi 是它之上的**产品层**：
补上个人上下文、长期目标与跨会话状态，并把二者组装成可独立使用的智能体。

> **当前状态（2026-11-24）**：可运行的纸墨工作台 + 长期记忆实验平台。
> 下表按"能用 / 实验 / 未做"分层，读者不必从正文中自行拼凑成熟度。标"实验"的部分
> 产品价值尚未证实，不作为能力承诺。
>
> | 能力 | 状态 | 依据 |
> |---|---|---|
> | 桌面窗口 / 离线演示模型 | 可用 | 219 项测试 + Qt 自渲染截图 + exe 自检 |
> | 真实模型接入（讯飞 spark-x2.6 / 百度百炼） | 可用 | 端到端实测，见 `docs/MODEL-GATEWAY-CANDIDATES.md` |
> | 个人事实 / 长期目标 / 会话持久化 | 可用 | 单测覆盖 |
> | 通讯协作（阶段 A/B/C，含外部智能体分级接入） | 可用 | 离线三智能体 + 真接入分级标注 |
> | **实操工具（文件读写 / 联网）** | **可用** | 18 工具，写操作带作用域 gate，见 `docs/PRODUCTION-TOOL-SILENT-FAILURE.md` |
> | 长期记忆层（temporal_memory） | 实验 | 评测口径与分数见 `docs/FINAL-SUMMARY.md` |
> | M2 进化引擎 | 实验 | 门控已接通，验证样本 0 条，尚无晋升 |
> | Event & Scheduler / 弱网适配 | 未做 | 见文末"尚未实现" |
>
> 许可证：**PolyForm Noncommercial 1.0.0**（禁止商用，见 `LICENSE`）。

## 设计边界（与 Core 的职责划分）

| 层 | 归属 | 职责 |
|---|---|---|
| 规划 / 路由 / 工具执行 / 权限 / 事件 / 收据 | YAI Agent Core | 单次任务怎么完成 |
| Personal Context（个人事实与偏好） | **YoAi** | 跨会话记住"用户是谁、偏好什么" |
| Goal Manager（长期目标与进度） | **YoAi** | 跨会话记住"要达成什么" |
| 门面 / CLI / 未来 Web·桌面壳 | **YoAi** | 把能力组装成终端产品 |

**与 Core 的边界**：Core 是产品内核、可以改，但改动必须能跟随 Core 自身更新。
当前所有改造都在 YoAi 侧——通过 Core 的公开扩展点（`AgentCore` / `discover` /
`RouteSelector` / 公开 Router 继承 / filesystem 电池）实现，`src/yai_core/` 零改动；
个人状态走自己的 JSON 存储。这样 Core 升级时天然兼容，不必 rebase 私有改动。

## 目录结构

```
src/yoai/
  context.py       Personal Context：个人事实持久化（原子写 + 损坏隔离）
  goals.py         Goal Manager：长期目标 CRUD + 状态流转
  capabilities.py   宿主业务能力（被 Core 内省成工具）
  agent.py          YoAiAgent 门面：组装 Core + Context + Goals
  routing.py        工具优先路由（有工具就注入完整 schema，消除静默失败）
  tools_builtin.py  实操工具：filesystem 电池（文件读写）+ 联网（搜索/抓取）
  temporal_memory.py 时间记忆层（YoAi 内覆盖层）
  session.py        SessionManager：会话隔离 + 历史持久化
  cli.py            命令行入口
tests/
  test_state.py     Context / Goals 持久化单测
  test_agent.py     工具内省 + 端到端事件流 + 默认模型
  test_routing.py   工具优先路由
  test_tools_builtin.py 文件读写 gate + 联网
  test_gateway_continuation.py 过渡语 re-ask
output/             本地状态（context.json / goals.json），gitignore
workspace/          实操工具的默认文件根目录（AI 可读写，写限子目录）
docs/               设计、根因案例、成绩与台账（见 docs/PROJECT-LEDGER-STATUS.md）
```

## 桌面 APP（真实窗口）

YoAi 是标准 Qt Widgets 桌面应用，采用纸墨工作台布局：左侧导航、中央对话、
右侧可收起上下文检查器。检查器显示可读执行步骤、个人事实、长期目标和本轮记忆写入；
通讯页与星球系页会切换成自己的上下文信息。离线演示模型可交互，无需 API Key。

先约定两个路径变量（下面所有命令都复用）：

```bash
export YOAI_ROOT=/path/to/YoAi          # 本仓库根目录
export CORE_ROOT=/path/to/YAI-Agent-Core # YAI Agent Core 源码根目录（产品内核，当前零改动）
export CORE_PY="$CORE_ROOT/.venv/Scripts/python.exe"  # Windows；Linux/macOS 去掉 .exe 与 Scripts/
export PYTHONPATH="$YOAI_ROOT/src;$CORE_ROOT/src"     # Linux/macOS 用冒号分隔
```

```bash
# 启动真实桌面窗口（Core venv 已装 PySide6）
"$CORE_PY" -m yoai.desktop.app

# 试试输入：
#   记住我偏好深色主题
#   创建一个目标：完成 YoAi 原型
#   列出我的目标
#   列出我记住的事实
#   在 notes 目录写一个文件 hello.txt，内容是你好
#   读一下 notes/hello.txt
#   搜索一下 Python 教程
```

界面消费 Core 的 21 类事件（路由/工具调用/授权/错误/完成等），把原始事件转成
可读步骤；工具参数与结果保留在检查器提示中，不混进最终回答。执行在后台 `QThread`
里跑 asyncio，不阻塞 UI。检查器在每次任务完成后自动刷新，个人状态落盘到 `output/`，
重启仍在。

无头验证（CI）：`QT_QPA_PLATFORM=offscreen python -m pytest` 运行完整测试套件。

## 独立 exe（可双击运行）

`dist/YoAi.exe` 是单文件应用（约 82 MB），**不依赖 Python、不依赖 Core venv**，
双击即开。个人状态保存在 exe 同目录的 `output/`，重启仍在；AI 的实操工具以
exe 同目录 `workspace/` 为根目录。

> ⚠️ 打包产物必须和源码同步：改完源码要重新构建，否则双击运行的是旧代码。
> 用自检确认产物里工具数为 **18**（12 记忆/目标 + 4 文件 + 2 联网）：
> `selfcheck.json` 的 `tools` 少于 18 就说明 exe 是旧的。

**单实例 + 干净退出**：同时只能开一个桌面实例，第二个启动会直接退出
（用 `QLocalSocket` 检测，进程异常终止时 OS 自动释放，不会留下"陈旧锁"）。
关闭窗口时会真正取消后台任务（worker 的 `requestInterruption` 会 cancel asyncio
任务），不再出现"窗口关了但 YoAi.exe 进程残留"。

**权限 3 档（Core 的 `AllowlistPolicy`）**：桌面用 `auto` 档而非默认的 `allow_all`：

| 档位 | 行为 |
|---|---|
| `allow_all` | 全放行（仅自检用，启动有安全警告） |
| **`auto`（桌面默认）** | 白名单内自动放行；白名单外弹窗等用户确认 |
| `deny_all` | 白名单外一律拒绝 |

白名单 = 只读工具 + 记忆/目标内部写入；**文件写（`file_create` / `file_patch`）必须弹窗确认**。
弹窗默认选中"拒绝"（失败关闭）；关窗时所有等待中的审批一律拒绝，绝不放行。
实现见 `src/yoai/desktop/approval.py`。

```bash
# 重新构建（需要 Core venv 里的 PyInstaller）
"$CORE_PY" build_exe.py

# 无控制台自检（脱离 venv 验证 exe 内部真的跑通）
QT_QPA_PLATFORM=offscreen "$YOAI_ROOT/dist/YoAi.exe" --self-check
# 结果写入 dist/output/selfcheck.json
```

构建配置见 `yoai.spec`：纳入 yoai 与 yai_core 两个源码树，PySide6 平台插件由官方
hook 收集，`console=False` 所以双击不弹黑框。

> 注意：exe 的 `--self-check` 用 offscreen 平台，不会弹窗；正式使用直接双击即可。

## 通讯协作（Phase 1.5 · 已实现阶段 A + B）

YoAi 内置社交式通讯：多个智能体作为 peer 接入同一个 `Channel`，可单聊、可拉群、
群内广播，每个 peer 用自己的 Core 实例独立思考并回复。桌面"通讯"标签页可建群、
拉人、实时看消息。全部离线可跑（3 个 DemoModel 智能体：小策/小满/老K）。

- 内核（`src/yoai/chat/`）：`Message` / `Group` / `AgentPeer` / `Channel` / `ChatStore`
- 防循环：只有 chat 消息触发 peer 回复，reply 不再触发；群广播排除发送者本人
- 并发：各 peer 独立 YoAiAgent 实例（契合 Core"一实例一会话"契约），`asyncio.gather` 并行投递
- 持久化：`output/chat/chat.json`（exe 模式为 exe 同目录），跨会话可查
- 边界：不改 Core 实现编排（当前 Core 源码零改动）、不做对等 Multi-Agent 编排，只做消息路由/群状态

`python -m pytest tests/test_chat.py tests/test_chat_ui.py` 覆盖内核与 UI（详见
[`docs/COMMUNICATION-PLAN.md`](docs/COMMUNICATION-PLAN.md)）。

> 阶段 C（外部智能体接入）已实现，见下节。

## 纸墨工作台与星球系 UI

桌面主窗口已重做为纸墨工作台：左侧导航、中央对话、右侧可收起上下文检查器。
默认纸色 `#F6F5F1` / 墨色 `#242522` / 朱砂 `#B64732`，深色主题使用冷 charcoal 底；
主界面不用渐变、玻璃或大面积阴影，动画只服务导航与检查器收放。

- `src/yoai/desktop/cosmic/theme.py`：纸墨/深色 tokens、完整 QSS、焦点与禁用状态。
- `src/yoai/desktop/widgets.py`：轨道标记、导航、消息、输入、检查器与记忆写入摘要。
- `src/yoai/desktop/cosmic/galaxy.py`：恒星=根节点、行星=专家、轨道=血统，点击看详情。
- `texture.py` / `planet.py`：程序化无缝贴图与固定光照自转，保留原有星球资产。
- `starfield.py`：星空只在深色主题且星球系标签可见时运行；隐藏或切走立即暂停。
- 通讯页使用“会话列表＋消息线程＋会话检查器”，不再重复显示主对话侧栏。

## M2 进化引擎（候选生成 + 隔离评测晋升）

`src/yoai/evolution/` 现在有完整的进化链：
- `CandidateGenerator`：只对 capability/routing 归因生成候选（**environment 问题不进化**），
  从**本次实际执行节点**派生，不覆盖父节点；diff 记录改动理由。
- `PromotionGate`：candidate→probation 靠隔离验证样本评测（样本不足/退化不晋升），
  probation→active 靠试用证据，退化→retired（保留档案）。
- `EvolutionEngine.evolve(evidence_id)`：归因→门控→候选→评测→晋升决策，产出可审计报告落盘。
- **诚实实测**：谎称记住未落盘 → 验收失败 → 生成候选，但验证样本 0 条 → 评测 insufficient
  → 不晋升，候选留在 candidate。引擎不自动在每次对话后触发（避免分支泛滥）。

> 边界：候选增强是朴素确定性规则（补工具/标签/提示），策略改写留未来。M3（预算内候选试验）、
> M4（长期指标）尚未实现。

## 证据基础设施（M2 前置 · 已打通）

日常每次对话自动采集**真实执行事件**（DONE/ERROR/TOOL_CALL/DiagnosticEvent），
落盘为带任务指纹 + 父节点 id + 样本类别的证据，并做三分归因：
- `src/yoai/evidence/`：`ExecutionEvidenceCollector` / `EvidenceStore` /
  `AttributionEngine` / `BenchmarkLab`。
- **诚实原则**：证据只来自真实事件流，不从模型自评生成；usage 拿不到就留空不臆造。
- **三分归因**：工具环境问题（DiagnosticEvent）/ 能力问题（OutcomeVerifier+DONE）/
  路由不适配（同类指纹历史成功率对比）；证据不足时低置信、不硬造分支。
- **样本隔离**：日常对话=进化样本；验证样本单独构造，`BenchmarkLab` 只用验证样本评测，
  报样本量 + Wilson 置信区间，样本不足不下晋升结论。
- **专家身份接入**：主对话用 `ExpertModelProvider` 包装，每次调用前由 M1 路由真实选专家，
  把选中专家的 `prompt_suffix` 注入 system（真参与执行）；证据记录 `expert_id` / `parent_id` /
  完整路由决策，归因据此定位"哪个专家在干活"。无可靠候选时回退根节点并记理由。
- **真实验收（OutcomeVerifier）**：`src/yoai/verification/` 默认开启——`ReceiptVerifier` 看执行收据，
  `StateAssertionVerifier` 查 PersonalContext 真实状态。核心防线：**DONE.status=ok 但状态没落盘
  时判 `verified_failure`**（模型谎称"已记住"也能抓到），验收结果流入证据，归因不再被 status 蒙蔽。
  无证据时诚实返回 `not_verifiable`，不假装验收过。
- 落盘位置：`output/evidence/evidence.json`（exe 模式为 exe 同目录）。

## 会话身份（不再每次新开对话）

桌面主对话顶部有会话下拉 + "新建"按钮：
- 每个 session = 一个独立 `AgentCore` + `SqliteStore(scope=session_id)`，历史按会话隔离；
- 切换会话即切到对应实例，**历史自动重载**；跨启动仍在（不新建、不丢历史）；
- 个人事实 / 长期目标跨会话共享（符合进化设计单"人格记忆不分裂"）；
- 实现见 `src/yoai/session.py`（`SessionManager`）。

> 关键实现细节：Core 的 `AgentLoop` 在构造时就绑定 memory，所以必须在 `AgentCore(memory=...)`
> 构造时传入持久化 store，事后替换无效——`YoAiAgent` 已支持 `memory=` 参数。

## 真实模型工具调用

真实模型能**自己决定调用工具**，当前共 18 个（12 记忆/目标 + 4 文件 + 2 联网）：
- 适配器透传 Core 的工具 schema 与完整对话（含 tool 结果轮），解析 `tool_calls` / `tool_use` 块；
- `GatewayModelProvider` 把结果转成 Core 的 `ToolCallRequest`，工具循环由 Core 统一治理；
- **工具优先路由**（`src/yoai/routing.py`）：有工具就一律注入完整 schema，让模型自己判断调不调。
  不再靠关键词表猜意图——旧做法会漏词导致"模型吐协议文本被拒"的静默失败（见
  `docs/PRODUCTION-TOOL-SILENT-FAILURE.md`）。
- **过渡语兜底**：模型若只说"我去查一下"却没真调工具，适配层自动追问一次再执行，
  不会把过渡语当最终答案（见 `docs/PRODUCTION-STALL-REASK.md`）。
- 历史实测（2026-11-21）：算里调用 `remember_fact(城市=杭州)`、DeepSeek 调用
  `remember_fact(宠物名字=旺财)`，落盘确认。

## 真实模型接入（当前：讯飞 · 2026-11-24）

YoAi 主对话与群聊 peer 都走 HTTP 网关（绕开被沙箱拦的 CLI 子进程）。
网关配置统一读 Core `.env` 的 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL`：

- **当前生产**：讯飞星辰 `spark-x2.6`（10 亿 token / 31 天，串行 12/12 稳定，
  tool_calls 实测完美）——`https://maas-api.cn-huabei-1.xf-yun.com/v2`。
- **可切换**：百度百炼（DeepSeek 同款模型，评测口径，16 并发稳定）；
  Groq / OpenRouter / DeepSeek 等兼容端点见 `docs/MODEL-GATEWAY-CANDIDATES.md`。
- 历史：算里 key 已于 2026-11-24 到期（401），不再可用；DeepSeek Anthropic 端点曾实测通过。

key 只在内存使用，不回显/不写盘/不进结果，usage 透传给预算。

主对话接法（一行换模型）：
```python
from yoai.models import DeepSeekAnthropicAdapter, GatewayModelProvider
agent = YoAiAgent(model=GatewayModelProvider(DeepSeekAnthropicAdapter()))
```
> 第一轮真实模型端到端测试（算里免费 DeepSeek：单轮对话 / 工具调用 / 多轮工具链）
> 已跑通，详见 [`docs/ROUND1-REAL-MODEL-TEST.md`](docs/ROUND1-REAL-MODEL-TEST.md)。

## 外部智能体接入（Phase 1.5 阶段 C）

通讯页左侧"外部智能体"清单列出本机 10 个智能体，**双击即可注册为 peer 并加入当前群**。
接入分三级，诚实标注、不伪装（实测清单见 [`docs/AGENT-PROBE.md`](docs/AGENT-PROBE.md)）：

- **L2 真接入**（自动回答）：Claude Code（`claude -p`）、OpenCode Zen（直连
  `https://opencode.ai/zen/v1` OpenAI 兼容 API，key 从 opencode 的 auth.json 读取，
  只在内存使用不回显）——子进程非交互 / API 直连 + 超时 + 错误翻译，结果作为群回复。
  > Zen 现状（2026-11-21 实测）：key 有效、69 模型可见，但付费模型返回 402 余额不足、
  > 免费模型返回 429 额度用尽。适配器已实现，充值/额度重置后立即可用；当前诚实报错不伪装成功。
  > 详见 [`docs/AGENT-PROBE.md`](docs/AGENT-PROBE.md)。
- **L1 仅唤起**（需人工转发）：Qoder / Qoder CN / Trae CN / MiniMax Code CN / ZCode /
  WorkBuddy / ChatGPT / DeepSeek Harness——本机只有 URL 协议或 GUI，无消息级 API；
  适配器把消息写进 `output/drops/*.md` 投递文件，回复靠人工贴回，**不伪造自动回答**。
- 统一 `PeerAdapter` 契约（`src/yoai/adapters/`）：外部调用带超时、可禁用、fail closed；
  注册表 `registry.py` 一处配置谁能接、怎么接。

> 说明：真实调用 Claude Code 时若当前环境禁用子进程（沙箱进程黑名单），
> 适配器会返回 `ok=False` 并写明原因，不会让群聊卡死或假装成功。

## 运行（开发环境 CLI / 测试）

项目未假定有 `uv`；沿用上面约定的 `YOAI_ROOT` / `CORE_ROOT` / `CORE_PY` / `PYTHONPATH`。

```bash
# 跑测试（离线、零 API Key）
"$CORE_PY" -m pytest -q

# 查看本地状态 / 已注册工具
"$CORE_PY" -m yoai.cli
"$CORE_PY" -m yoai.cli --tools

# 单次任务（默认占位模型，演示事件流）
"$CORE_PY" -m yoai.cli "你好"
```

## 接真实模型

只换模型注入一行（Core 侧 `[llm]` extra，OpenAI 兼容 DeepSeek / 通义 / OpenAI）：

```python
from yai_core import OpenAICompatProvider
from yoai import YoAiAgent

agent = YoAiAgent(model=OpenAICompatProvider())
```

## 安全提醒（使用前必读）

**默认 `allow_all`：工具免审批自动执行。** `AgentCore` 起步阶段使用 Core 的默认
`allow_all` 权限策略，Core 会打印 `ProductionSafetyWarning`。这不是生产配置：

- 生产 / 多用户环境必须显式配置 `PermissionPolicy` 或设 `auto_approve_tools=False`，
  见 Core 的 `docs/guides/production-permissions.md`。
- **接入外部智能体或处理不可信内容时尤其要收紧**：通讯页可把本机智能体注册为 peer，
  任一 peer 读到不可信内容后，全放行策略会让注入沿调用链触达工具写操作。这是当前
  架构最需要警惕的失效模式，不是已修复项。
- OpenCode Zen 的 key 只从本机 `auth.json` 读入内存，不回显、不写盘；本项目不自带
  任何凭据。

## 尚未实现 / 已知边界

- Event & Scheduler：事件响应、周期任务、长任务中断恢复。
- 实操工具的边界：文件仅限 `workspace/`（写限白名单子目录，带作用域 gate），
  联网仅只读的搜索/抓取（无终端、无桌面控制、无写外部系统）。
- 弱网 / 低带宽适配、手机自动化：未做。
- 长期记忆高级能力：语义召回、时间版本、冲突解决。
- 进化引擎 M3（预算内候选试验）、M4（长期指标）：未实现；当前验证样本 0 条，
  晋升门控不会在无证据时放行。
- 评测脚本在 `bench/`，结果归档在 `bench_results/`，不属于桌面默认执行路径。
