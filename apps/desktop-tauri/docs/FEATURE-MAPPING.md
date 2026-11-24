# YoAi 桌面功能对应清单（PySide6 旧版 → Tauri 新版）

> 依据实际调用链核对（非文件名推断），以源码为准。旧版保留可启动作为回退。

## 功能对应表

| 能力 | 旧版（PySide6）调用链 | 新版（Tauri）状态 | 说明 |
|---|---|---|---|
| Agent Core 接入 | `app.py:_build_main_model` → `YoAiAgent` → `AgentCore` | ✅ 已迁移 | runtime 复用同一构造路径，内核零改动 |
| 事件流接收 | `worker._consume` → `event_received.emit` | ✅ 已迁移 | Python stdout JSONL → Rust emit → React |
| 文本流式上屏 | `delta` 事件 → `ChatView.append_stream_text` | ✅ 已迁移 | `useTaskStream.streamText` 按 round 累积 |
| thinking 展示 | `thinking` 事件 → `think_buffer`（默认折叠） | ✅ 已迁移 | `ProcessPanel` 默认折叠 + 查看入口 |
| 执行过程面板 | `ChatView` 过程块（QTextBrowser 全量重渲染） | ✅ 已迁移+改进 | TanStack Virtual 虚拟化，实时区/历史分离 |
| 工具调用卡片 | `_on_event(tool_call/tool_result)` → trace + 正文 | ✅ 已迁移 | `toolCards()` + tool-card 样式 |
| 任务停止 | `AgentWorker` cancel | ✅ 已迁移 | `task.cancel` 命令 → asyncio cancel |
| 完成/失败/取消 | `_on_done/_on_error` + status | ✅ 已迁移 | `status` 消息四态 + `final` 定稿 |
| 用户确认（审批） | `ApprovalChannel.ask` → Qt 弹窗 | ✅ 已迁移 | 复用 Core `SidecarChannel` → `approval.request` → React 弹窗 |
| 澄清补充输入 | 同上 clarify | ✅ 已迁移 | `clarify_requested` 事件 + `clarify.reply` 命令（UI 待接输入框） |
| 专员切换 | `ExpertModelProvider` 路由 + UI 选择 | 🟡 部分迁移 | UI 选择器已接，`last_expert_id` 回显待补；路由本身在内核自动生效 |
| 会话管理 | `SessionManager` create/switch/touch | 🟡 部分迁移 | runtime 定义了 session.list/switch；设置页 UI 待补 |
| Markdown 渲染 | `markdown_html.py`（手写） | ✅ 已迁移+改进 | `react-markdown` + gfm（表格）+ highlight |
| 代码块复制 | 无 | ✅ 新增 | `CodeBlock` 复制按钮 |
| 设置持久化 | 旧设置页 → config.json | ⏳ 待迁移 | `config.get/set` 命令已定义，设置页 UI 待补 |
| 悬浮模式 | 旧 QML 悬浮窗 | 🟡 部分迁移 | 胶囊形态 + 点击展开已实现；**拖动/位置记忆/DPI 待补** |
| 系统托盘 | Qt QSystemTrayIcon | ✅ 已迁移 | Tauri `TrayIconBuilder` + 菜单 |
| 窗口生命周期 | 单实例守卫 + 退出清理 | ✅ 已迁移 | Rust 管理子进程；`shutdown` + kill/wait |
| 后台进程退出 | 旧进程残留 bug 已修 | ✅ 已迁移 | Destroyed 事件发 shutdown + kill/wait |
| 多显示器/DPI | Qt 默认处理 | ⏳ 待迁移 | Tauri 需显式处理（阶段 D 未完成项） |
| 学习状态界面 | 旧 learning vault 面板 | ⏳ 待迁移 | 非核心，P2 |
| 代码工具仓库 | 旧 tool vault 面板 | ⏳ 待迁移 | 非核心，P2 |
| 证据采集/benchmark | 旧 worker 旁路落盘 | ⏳ 待迁移 | `bench/` 评测不走桌面端，保持独立 |

## 图例

- ✅ 已迁移：有真实调用链与代码，且经过至少离线测试
- 🟡 部分迁移：命令/数据通路在，UI 或细节待补
- ⏳ 待迁移：明确未完成，不假装完成

## 内核改动

**零改动**：新版只新增 `apps/desktop-tauri/**`，复用 `yoai.agent.YoAiAgent.astream`
与 Core `SidecarChannel`。旧 PySide6 桌面端 `src/yoai/desktop/**` 未删除未修改。
