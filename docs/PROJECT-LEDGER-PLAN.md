# 项目台账二 · 计划（接下来做什么）

> 2026-11-23 建立。只记录待办，不写已完成（完成项移入 `PROJECT-LEDGER-STATUS.md`）。

| # | 待办 | 状态 | 下一步 | 需拍板 |
|---|---|---|---|---|
| 9 | **Core 更新：thinking/signature 块回传** | **待转发** | 把 `docs/CORE-UPDATE-REQUEST.md` 转给 Core 负责人；这是唯一真需要 Core 改的项（ModelResponse.raw 有原始块但 loop 构造 assistant 消息时丢弃） | 你（转发） |
| 10 | Anthropic thinking 坑的本地绕法 | 未做 | 在 Core 修好前，评估换不带 thinking 的 `ANTHROPIC_MODEL`（治标）或 `ModelResponse.raw` 侧回注；见 ANTHROPIC-TOOL-RESULT-400.md | — |
| 3 | 进化机制重启 | 暂停 | 解决"工具白名单限制反降分"根因 | — |
| 6 | UI 美化 | 后置 | — | — |
| 7 | README 对外版 | 后置 | 已更新到当前状态（228 测试/18 工具/权限 3 档），但仍偏内部视角，面向开源访客重写 | — |
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

## 维护约定

- 完成一项 → 从本表移除或标完成，结果写进状态台账对应行。
