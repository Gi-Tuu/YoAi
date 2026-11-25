# 右侧工具方格（2026-11-26）

在原有「个人事实 / 长期目标 / 本轮记忆」三张卡片下方新增一排三格：
**浏览器 / 终端 / 查看文件**。点方格展开工具面板，再点一次或点 × 收起。

## 浏览器

- 地址栏只接受 `http://` / `https://`，内嵌 `iframe` 直接显示；
- 站点用 `X-Frame-Options` / CSP 禁止内嵌时，点「系统打开」走 runtime 的
  `browser.open` → 标准库 `webbrowser`，仍只校验 http/https，不给 shell 能力；
- 失败通过 `error(stage=browser)` 回到面板提示。

## 终端

- 面板**不绕过权限**：输入命令后作为普通任务发给 YoAi，提示它调用 `shell_run`；
  smart/manual 档位的审批仍在对话区完成，full 档才免审批；
- 面板按 `run_id` 收集该任务的 `tool_result(shell_run)` 与错误事件展示输出，
  同时保留完整执行记录在对话区，审计链不变；
- 因此终端面板是「命令入口 + 结果视图」，不是独立的无审批 shell。

## 查看文件

- runtime 新增只读 `fs.list` / `fs.read`：
  - 项目模式会话 → 根目录为绑定的项目文件夹；
  - 聊天模式会话 → 根目录为 `<data_dir>/workspace`；
  - 路径统一走 `resolve_in_project()`，`..` 与符号链接逃逸一律拒绝；
- 只返回文本（UTF-8 容错解码），单次最多 20 万字符并标记 `truncated`；
- 目录/文件均在面板内导航，根目录按钮 `title` 显示实际绝对路径便于核对。

## 改动位置

- `apps/desktop-tauri/src/components/ToolDock.tsx`（三格与面板）
- `apps/desktop-tauri/src/App.tsx`（`right-rail` 布局、终端任务入口）
- `apps/desktop-tauri/src/styles/app.css`（方格/面板样式）
- `apps/desktop-tauri/runtime/{protocol.py,yoai_runtime.py}` 及两份同步副本
- `src/types/ipc.ts`、`src/lib/ipc.ts`、`docs/IPC-PROTOCOL.md`（协议同步）

内核零改动：全部是 YoAi 侧 UI 与 runtime 能力。
