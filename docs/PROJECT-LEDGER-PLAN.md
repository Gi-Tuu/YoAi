# 项目台账二 · 计划（接下来做什么）

> 2026-11-23 建立。只记录待办，不写已完成（完成项移入 `PROJECT-LEDGER-STATUS.md`）。

| # | 待办 | 状态 | 下一步 | 需拍板 |
|---|---|---|---|---|
| 3 | 进化机制重启 | 暂停 | 解决"工具白名单限制反降分"根因 | — |
| 6 | UI 美化 | 后置 | — | — |
| 7 | README 对外版 | 后置 | 已更新到当前状态（228 测试/18 工具/权限 3 档），但仍偏内部视角，面向开源访客重写；模型迁移后测试数已变 240 | — |
| 8 | judge 换官方 gpt-4o | 未做 | 需 OpenAI key；唯一无法靠免费额度解决的项 | — |

> 项 2（生产侧记忆写入保障）**已完成并移出**：真实生产验证兜底接管成功、
> 中文事实信号 bug 已修，结果见状态台账。B/C 仍默认关（opt-in），
> "是否需要改默认"转为观察项，不再单列待办。

## 2026-11-24 已完成（从计划移出，结果见状态台账）

- DIRECT 静默失败根治（工具优先路由）
- UI 错误可见（error 事件显示 + 部分失败状态）
- 实操工具 18 个（文件读写 + 联网，写有 gate）
- 过渡语 re-ask（模型只说"我去查"不执行）
- exe 未更新 / session 路径开关遗漏（重新打包 + 自检验证）
- 进程残留 + 多实例（真 cancel + QLocalSocket 单实例）
- Core 权限 3 档落地（auto + 审批弹窗，allow_all 环境变量开关）
- Anthropic tool_result 400（改用 Core 官方转换，thinking 坑转项 10）
- ~~#9 Core thinking 更新~~：**已合并**——thinking 分支 d4a2204 已 fast-forward 进 Core main
  （用户拍板"都是我的项目，帮我合并"，无需再转发需求），Core 测试 63 passed
- ~~#10 thinking 本地绕法~~：**不再需要**——主对话已迁到 Core 官方 AnthropicProvider，
  thinking 块回传自动生效；见 MODEL-MIGRATION-CORE-ANTHROPIC.md

### 2026-11-24 晚 · 产品能力补全（已完成，从计划移出）

- 工具热加载（旧会话不重启 + 插件目录 mtime 加载）
- 基础实操：`shell_run` 受限终端（审批弹窗）+ `open_url` 系统浏览器
- 消息 Markdown 渲染（含表格；先转义后解析防注入）
- 执行过程/thinking 正文可见 + DONE 后折叠（可展开回看）
- 真·token 流式输出（Anthropic 与桌面 Suanli SSE 两条路径均验证；`YOAI_STREAM=0` 回退）
- 思考碎片合并成一段 + 默认折叠只留入口
- 全部文档见 `TERMINAL-AND-BROWSER.md` / `MARKDOWN-RENDERING.md` /
  `PROCESS-AND-THINKING-UI.md` / `STREAMING-OUTPUT.md`；总览第九节已同步

## 维护约定

- 完成一项 → 从本表移除或标完成，结果写进状态台账对应行。

### 2026-11-25 · 旧端UI搬迁与清理（已完成，从计划移入）

- 旧 PySide6 端 UI 全部能力搬入 Tauri 新端 + 旧端源码清理删除（28 删除/13 修改/4 新增）
- 详见 `docs/OLD-UI-MIGRATION.md`
- GUI 目视验证已完成并 commit；当前为稳定态

### 2026-11-25 下午 · 已关闭的事项

- 原生浮窗（悬停出桌面）：5 轮尝试全部白屏，已放弃并回退（提交 b74379a）；
  结论写进项目 MEMORY.md 与 DESKTOP-SWITCH.md，不再重试
- 模型总时长硬上限（60s→180s 均误杀长推理）：默认取消（`model_timeout=None`）；卡住靠 socket 读超时、重连靠 transport_retries；`YOAI_MODEL_TIMEOUT=<正数>` 可显式加回
- 只读工具可发现性（模型误判"能力缺失"）：已修描述文案 + 回归测试
- 残留调试环境变量 `YOAI_RUNTIME_LOG`：已清除（用户级）

### 2026-11-26 · 已关闭的事项

- 模型总时长上限误杀长推理：默认取消，卡住/重连交给传输层（见上）
- 右侧工具方格：浏览器 / 终端 / 查看文件三格已加到现有三卡下方，均为可用面板；
  终端不绕过审批，文件面板只读且锁在项目根/workspace；见 `docs/TOOL-DOCK.md`
- 消息动作与附件：设计已拍板并实施，归属矩阵见 `docs/MESSAGE-ACTIONS-DESIGN.md`；
  软删除+分支、文本抽取附件、本地 md/html 分享
- RSI 全链（R0~R5）、MCP（stdio/HTTP/SSE）、Skill（脚本包/市场/签名链/CT/R4 元策略）
  已实施并推送，详见状态台账与 `FINAL-SUMMARY.md` 第十节。
- R5 技能页 GUI 目视验证：20:37 你确认通过，CT 状态/按钮/透明日志展示正常，无代码改动。

### 2026-11-27 · 已关闭的事项

- 定时任务 S1/S1.1/S2：默认关闭，五份 runtime 同步，全量 377 passed + 3 skipped；
  13:52 真实 Core + 真实模型一次性任务 smoke 通过（`state=ok`，无弹窗/无被拒工具）。
  PR #1 已 squash 合并进 `master`（`67542be`）；CI 曾因 Linux venv 路径假设失败，
  已用 `41f28a9` 修正测试后 CI pass。
- S4 前端定时页方案与实机 smoke 清单已落文档（`SCHEDULER-S4-UI-PLAN.md` /
  `SCHEDULER-SMOKE-CHECKLIST.md`），**代码未写**。

## 当前待办（2026-11-27 14:00 口径）

上表 #3（进化机制重启）、#6（UI 美化）、#7（README 对外版）、#8（judge 换官方
gpt-4o）仍有效；其中 #8 是唯一依赖外部 key 的项目。新增/细化的当前项：

| # | 待办 | 状态 | 下一步 | 需你拍板 |
|---|---|---|---|---|
| 9 | RSI 真实数据观察期 | 进行中 | 正常使用积累反馈与边界证据；某标签样本 ≥20 且状态 weak 才生成候选，不硬造 | — |
| 11 | 公网 CT 服务 / gossip 审计 | 范围外 | 当前只校验外部 CT 回执，不自动提交；若纳入产品默认需另起服务设计与运维 | 是否纳入 |
| 13 | S4 前端「定时」页 | 设计完成 | 按 `SCHEDULER-S4-UI-PLAN.md` 实现列表/表单/记录/状态条 + IPC + 前端测试 | — |
| 14 | S3 对话 `schedule_*` 工具 | 未做 | 让用户用自然语言创建/取消任务；不进无人值守白名单 | — |
| 15 | S5 GoalManager 钩子与完整恢复 | 未做 | 目标创建/状态变化事件、中断恢复；依赖真实使用反馈 | — |
