# YoAi 通讯协作里程碑（Phase 1.5）规划

> 需求：做一个通讯界面，任意智能体都能接入形成通讯通道，在 YoAi 里像社交软件一样
> 互相交流、共同工作、可拉群。
> 排期判断：桌面 exe（Phase 1 交互入口）之后、长期记忆专项（Phase 2）之前。
> 本文是规划，不含已实现代码；实现进度以 README 与测试为准。

## 一、定位与边界（先划红线）

这是**产品层**能力，不是内核能力。

- YAI Agent Core 明确不做"对等 Multi-Agent 编排"（架构红线 §7），只做层级式
  子员工委派（`shell/employee`）。因此**不修改 Core 源码**、不把通讯塞进内核。
- YoAi 通讯层建在 Core 之上：每个接入的智能体 = 一个独立的 `YoAiAgent` 实例
  （Core 的并发契约是"一实例一会话，要并发就多实例"，正好契合）。
- 通讯层只负责"消息路由 / 群状态 / 身份与权限 / UI"，智能体内部怎么思考仍由各自
  的 Core 实例决定。YoAi 不重新发明 Agent。

## 二、复用 Core 已有能力

| 需求 | 复用 Core 的什么 | 不重造 |
|---|---|---|
| 智能体间传消息 | Sidecar 协议（stdio NDJSON + JSON-RPC 2.0，`YOAI` 可派生自有通道） | 不另造 RPC 框架 |
| 外部智能体接入 | A2A 1.0 定位 + 宿主适配器（`examples/host_a2a_adapter`） | 不实现 A2A 协议本身 |
| 子智能体委派 | `shell/employee` 层级委派、预算收窄 | 不做对等协商 |
| 身份与授权 | `Subject` 可信主体 + `PermissionPolicy` + capability gate | 不自建鉴权模型 |
| 执行留痕 | 21 类事件流 + 执行收据哈希链 | 不自建审计日志 |

## 三、三阶段路线

### 阶段 A：本地多智能体消息内核（先打通"能互相说话"）

- 定义 `AgentPeer`：一个接入 YoAi 的智能体，持有 id / 名称 / 能力清单 / 一个
  `YoAiAgent` 实例（本地）或远端通道（阶段 C）。
- 定义 `Message`：sender / recipients（单聊或群）/ content / timestamp / type。
- 定义 `Channel`：消息总线，支持点对点与群广播，投递到目标 peer 的任务入口。
- 群组 `Group`：成员列表、群消息历史（落盘到 `output/chat/`，复用 Context 的原子写思路）。
- 验收：本地起 3 个 DemoModel 驱动的 peer，A 发消息 → B、C 收到并各自回复，
  能拉群、群内广播，全程离线可测。

### 阶段 B：群聊 UI（像社交软件）

- 在现有 Qt 主窗口加"通讯"标签页：会话列表（单聊/群）、消息气泡区、输入框。
- 群组管理：新建群、拉人、退群、群成员在线状态。
- 与现有对话区并存：单聊即"和一个智能体对话"，群聊即"多智能体协作"。
- 消息到达走 `QThread` signal（复用现有 worker 模式），不阻塞 UI。
- 验收：offscreen 测试覆盖建群→拉人→发消息→成员回复→消息渲染全链路。

### 阶段 C：外部智能体接入协议（任意智能体可接入）

- 定义 `PeerAdapter` 契约：`connect / send / on_message / capabilities`。
- 三种内置适配器：本地 `YoAiAgent` 直连、Sidecar 通道（跨进程/跨语言）、
  A2A 宿主适配器（对接遵循 A2A 的外部智能体）。
- 接入即声明能力与信任级别；未知来源默认只读、需宿主授权才能发消息（fail closed）。
- 验收：用一个外部 Python 进程经 Sidecar 接入，发消息进群，群内其他 peer 可见。

## 四、与计划书原路线的关系

- 原 Phase 3"持续自主执行"：群聊里的多智能体协作可复用其长任务恢复机制，
  但通讯层本身不依赖 Phase 3 完成。
- 原 Phase 5"生态化与垂直扩展"：阶段 C 的 `PeerAdapter` 就是"独立能力适配器"
  的一种，提前落地不算越界。
- 不冲击 Benchmark：通讯层是协作能力，不伪装成记忆/工具基准成绩。

## 五、当前状态

- [x] 阶段 A：本地消息内核（`src/yoai/chat/`，6 项测试通过）
- [x] 阶段 B：群聊 UI（桌面"通讯"标签页，3 项测试通过）
- [x] 阶段 C：外部接入协议（`src/yoai/adapters/`，契约 + 10 个智能体注册表）
- [x] 排期与边界规划（本文）

> 阶段 A/B/C 均已落地。C 的诚实结论（见 `AGENT-PROBE.md`）：
> - **L2 真接入**（CLI 非交互 + 自动回答）：Claude Code（`claude -p` 实测成功）、
>   OpenCode（`opencode run` 接口正确，本机模型/网络未就绪）。
> - **L1 仅唤起**（URL 协议/可执行文件 + 投递文件，需人工转发，不伪造回答）：
>   Qoder、Qoder CN、Trae CN、MiniMax Code CN、ZCode、WorkBuddy、ChatGPT、DeepSeek Harness。
> 统一 `PeerAdapter` 契约容纳三种级别；外部调用带超时、可禁用、fail closed。
> 阶段 C 的 L2 真接入在沙箱环境里被进程黑名单拦过一次（reg.exe），属执行环境限制，
> 直连 bash 调用 claude 成功，真实双击 exe 环境不受此沙箱影响。
