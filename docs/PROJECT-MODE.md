# 项目模式（2026-11-25 晚）

## 设计（所有者拍板）

智能体是干活的，该有生产基础。两种模式并存：

- **聊天模式（默认）**：会话留在沙箱，无项目写工具，记忆全局共享——行为与改造前完全一致
- **项目模式**：会话绑定一个宿主机文件夹（"项目"），挂载 `proj_*` 读写工具，记忆按项目隔离

用户主动选"允许完全访问"档，即表示愿意独自担责——项目写不再弹窗。

## 实现

- `src/yoai/project.py`：`Project` 数据 + `ProjectStore`（CRUD，`<data_dir>/projects/projects.json`），
  `resolve_in_project()` 严格限制路径在项目根内（含符号链接逃逸防护）
- `src/yoai/project_tools.py`：`proj_list/proj_read/proj_write/proj_patch`，内核零改动。
  写带乐观并发校验（sha256，对齐 Core 的 file_patch 语义）
- `Session` 加 `mode`/`project_id`；`SessionManager` 支持按会话注入 agent kwargs 与记忆目录
- 权限联动：`proj_list/proj_read` 进 smart 自动白名单；`proj_write/proj_patch` 不在白名单
  → full(allow_all) 直接放行，smart/manual 走既有审批弹窗
- runtime 命令：`project.create`（建项目+建项目会话）、`project.list`、`project.delete`、
  `session.new_in_project`；snapshot 携带 `projects`
- 前端：会话抽屉内"项目"面板，原生文件夹选择器（Tauri dialog 插件）建项目，
  项目列表点一下即在该项目内新建对话

## 边界与约束

- 项目写工具**只能写项目文件夹内**，越界（含 `..`/符号链接）一律拒绝
- 删除项目定义不删会话历史；相关会话退回聊天模式语义
- 已有会话不自动归类，逐步新建即可
- 文件夹选择器选的是宿主机真实路径；路径存在性/目录校验在 runtime 侧

## 验证

- `tests/test_projects.py` 4 项：CRUD/路径校验、写工具闭环与越界、项目工具挂载与记忆隔离、权限联动
- 端到端（真实 runtime）：建项目→项目会话 mode=project→proj_write 真实落盘→
  切聊天会话后 proj_* 工具消失
- 全量 Python 262 passed + 1 skipped；前端 13 passed；Rust 编译（含 dialog 插件）通过
