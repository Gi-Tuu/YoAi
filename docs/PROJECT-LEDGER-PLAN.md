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
- 待办：GUI 目视验证（需用户实际打开 dist/YoAi.exe）；确认后 commit
