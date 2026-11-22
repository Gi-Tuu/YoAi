# YoAi — 个人自主智能体

基于 [YAI Agent Core](../../Competition/YAI%20Agent%20Core) 构建的开源个人智能体。
Core 是嵌入式自适应内核（规划 / 工具 / 治理 / 事件流），YoAi 是它之上的**产品层**：
补上个人上下文、长期目标与跨会话状态，并把二者组装成可独立使用的智能体。

> 当前状态：**Phase 0 起步骨架**（v0.0.1）。最小端到端闭环已跑通，10 项离线测试全绿。
> 这不是完整产品，详见文末"尚未实现"。

## 设计边界（与 Core 的职责划分）

| 层 | 归属 | 职责 |
|---|---|---|
| 规划 / 路由 / 工具执行 / 权限 / 事件 / 收据 | YAI Agent Core | 单次任务怎么完成 |
| Personal Context（个人事实与偏好） | **YoAi** | 跨会话记住"用户是谁、偏好什么" |
| Goal Manager（长期目标与进度） | **YoAi** | 跨会话记住"要达成什么" |
| 门面 / CLI / 未来 Web·桌面壳 | **YoAi** | 把能力组装成终端产品 |

红线：**不侵入 Core**。`src/yai_core/` 零改动；YoAi 只通过 Core 的公开 API
（`AgentCore` / `discover` / 事件流）接入，个人状态走自己的 JSON 存储。

## 目录结构

```
src/yoai/
  context.py       Personal Context：个人事实持久化（原子写 + 损坏隔离）
  goals.py         Goal Manager：长期目标 CRUD + 状态流转
  capabilities.py  宿主业务能力（被 Core 内省成工具）
  agent.py         YoAiAgent 门面：组装 Core + Context + Goals
  cli.py           命令行入口
tests/
  test_state.py    Context / Goals 持久化单测
  test_agent.py    工具内省 + 端到端事件流 + 默认模型
output/            本地状态（context.json / goals.json），gitignore
```

## 桌面 APP（真实窗口）

YoAi 是标准 Qt Widgets 桌面应用：左侧对话区（回车发送），右侧三栏实时显示
Core 的工具调用链、个人事实与长期目标。离线演示模型可交互，无需 API Key。

```bash
# 启动真实桌面窗口（Core venv 已装 PySide6 6.11.2）
cd E:/agent/YoAi
PYTHONPATH="E:/agent/YoAi/src;E:/Competition/YAI Agent Core/src" \
  "E:/Competition/YAI Agent Core/.venv/Scripts/python.exe" -m yoai.desktop.app

# 试试输入：
#   记住我偏好深色主题
#   创建一个目标：完成 YoAi 原型
#   列出我的目标
#   列出我记住的事实
```

界面消费 Core 的 21 类事件（路由/工具调用/授权/错误/完成等），逐条渲染到
"过程 / 工具链"栏；执行在后台 `QThread` 里跑 asyncio，不阻塞 UI。
侧栏在每次任务完成后自动刷新，个人状态落盘到 `output/`，重启仍在。

无头验证（CI）：`QT_QPA_PLATFORM=offscreen python -m pytest` 会跑桌面端 3 项测试。

## 独立 exe（可双击运行）

`dist/YoAi.exe` 是单文件应用（约 81 MB），**不依赖 Python、不依赖 Core venv**，
双击即开。个人状态保存在 exe 同目录的 `output/`，重启仍在。

```bash
# 重新构建（需要 Core venv 里的 PyInstaller 6.22.3）
"E:/Competition/YAI Agent Core/.venv/Scripts/python.exe" build_exe.py

# 无控制台自检（脱离 venv 验证 exe 内部真的跑通）
QT_QPA_PLATFORM=offscreen "E:/agent/YoAi/dist/YoAi.exe" --self-check
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
- 边界：不侵入 Core、不做对等 Multi-Agent 编排（Core 红线），只做消息路由/群状态

`python -m pytest tests/test_chat.py tests/test_chat_ui.py` 覆盖内核与 UI（详见
[`docs/COMMUNICATION-PLAN.md`](docs/COMMUNICATION-PLAN.md)）。

> 阶段 C（外部智能体接入）已实现，见下节。

## 宇宙星球系 UI（对齐 AMBRACE 服务器控制台 d2.css 原值）

桌面主窗口新增"星球系"标签。**严格照参考设计系统重做**（非深空蓝，而是暖砖红纸墨）：
- 双主题：纸墨 `#f4f0e6` ↔ 墨纸 `#131110`，砖红 `#8c3f2b` / 朱红 `#d8452a`；
  硬约束：零圆角 / 无阴影 / 装饰强调色每页≤6处 / 星空只进墨纸档。
- `src/yoai/desktop/cosmic/`：
  - `texture.py`：程序化生成 512px 无缝贴图（灰岩月海+撞击坑 / 橙色湍流黑子），
    纯 Qt 实现（无 PIL 依赖），启动缓存约 4 秒一次性。
  - `planet.py`：**贴图平移自转，光照层固定**——纹理转而光不转（物理正确）；
    星环拆球前/球后两截按物理遮挡。生命周期：active 朱红太阳 / probation 琥珀 /
    candidate 灰月 / retired 深赭。
  - `starfield.py`：星点亮度走 smoothstep 缓坡(28%-72%)无竖断层，亮星层 14s 呼吸，
    流星亮头在前、opacity 只前 11%（纸色档无星空）。
  - `planet_scrollbar.py`：球+3卫星+速度尾迹、可拖动的星球滚条（原生滚条藏掉）。
  - `dark_orb.py`：左下角只露上弧的暗星球 + 浮动卫星入口。
  - `galaxy.py`：恒星=根节点、行星=专家、轨道=血统，点击看详情。
- **按需不做开屏动画**（用户明确不要）。

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

真实模型（DeepSeek / 算里）现在能**自己决定调用个人工具**：
- 适配器透传 Core 的工具 schema 与完整对话（含 tool 结果轮），解析 `tool_calls` / `tool_use` 块；
- `GatewayModelProvider` 把结果转成 Core 的 `ToolCallRequest`，工具循环由 Core 统一治理；
- 实测：算里调用 `remember_fact(城市=杭州)`、DeepSeek 调用 `remember_fact(宠物名字=旺财)`，
  落盘确认。
- 边界：路由选 direct 时不给模型工具（Core 规则），多步骤任务会选 plan/react 触发工具调用。

## 真实模型接入（已验证 · 2026-11-21）

YoAi 主对话与群聊 peer 都能用真实模型，走 HTTP 网关（绕开被沙箱拦的 CLI 子进程）：

- **DeepSeek (Anthropic)**：环境变量 `ANTHROPIC_BASE_URL` / `AUTH_TOKEN` / `MODEL`
  → `api.deepseek.com/anthropic`，实测 HTTP 200 + 真实回答（跳过 thinking 块取 text）。
- **算里 DeepSeek**：Core `.env` 的 `OPENAI_BASE_URL` / `API_KEY` / `LLM_MODEL`
  → `api.suanli.cn/v1`，实测 HTTP 200 + 真实回答。

两者 key 只在内存使用，不回显/不写盘/不进结果，usage 透传给预算。

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

项目未假定有 `uv`；以下用 Core 自带的 Python 解释器 + PYTHONPATH 注入源码路径。

```bash
# 跑测试（离线、零 API Key）
cd E:/agent/YoAi
PYTHONPATH="E:/agent/YoAi/src;E:/Competition/YAI Agent Core/src" \
  "E:/Competition/YAI Agent Core/.venv/Scripts/python.exe" -m pytest -q

# 查看本地状态 / 已注册工具
PYTHONPATH="E:/agent/YoAi/src;E:/Competition/YAI Agent Core/src" \
  "E:/Competition/YAI Agent Core/.venv/Scripts/python.exe" -m yoai.cli
PYTHONPATH="E:/agent/YoAi/src;E:/Competition/YAI Agent Core/src" \
  "E:/Competition/YAI Agent Core/.venv/Scripts/python.exe" -m yoai.cli --tools

# 单次任务（默认占位模型，演示事件流）
PYTHONPATH="E:/agent/YoAi/src;E:/Competition/YAI Agent Core/src" \
  "E:/Competition/YAI Agent Core/.venv/Scripts/python.exe" -m yoai.cli "你好"
```

## 接真实模型

只换模型注入一行（Core 侧 `[llm]` extra，OpenAI 兼容 DeepSeek / 通义 / OpenAI）：

```python
from yai_core import OpenAICompatProvider
from yoai import YoAiAgent

agent = YoAiAgent(model=OpenAICompatProvider())
```

## 安全提醒

起步阶段 `AgentCore` 使用默认 `allow_all` 权限策略（Core 会打印
`ProductionSafetyWarning`）：工具免审批自动执行。生产 / 多用户环境必须显式配置
`PermissionPolicy` 或设 `auto_approve_tools=False`，见 Core 的
`docs/guides/production-permissions.md`。

## 尚未实现（Phase 1+）

- Event & Scheduler：事件响应、周期任务、长任务中断恢复（计划书 §3.2）。
- 真实工具集成：文件、终端、浏览器、桌面（Core 已有 Browser/Desktop Provider，待接入）。
- Long-Term Memory 高级能力：语义召回、时间版本、冲突解决（复用 Core 的 MemoryVault）。
- Benchmark：LoCoMo / LongMemEval 的 YoAi 层对照实验与结果归档。
- 独立安装包与 Web / 桌面交互入口。
