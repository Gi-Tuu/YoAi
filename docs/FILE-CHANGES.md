# 产物与文件改动卡片（2026-11-25 晚）

## 设计（所有者要求加入产品）
对齐主流 IDE Agent 的 UI：
- **产物（Artifact）**：Agent 新建的文件，列出文件名/大小，可下载
- **文件改动（Change Set）**：一次任务改了哪些文件，逐文件 +X/-Y，点击开展**行级 diff**

## 实现（产品侧，内核零改动）
- `src/yoai/file_changes.py`：FileChangeStore，记录每次项目写操作（路径/action/前后全文/
  added/removed/行级 diff ops），落盘 `<data_dir>/file_changes.jsonl`，上限 200 条；
  `line_diff()` 用 difflib 生成行级操作。
- `project_tools.py` 的 proj_write/patch 成功后经 `on_change` 回调记录（runtime 注入 store + session/project context）。
- runtime：snapshot 带 artifacts/changes；done 前推 `file.changed` 事件供前端实时追加。
- 前端 `FileChanges.tsx`：产物卡片（下载）+ 改动摘要（N 个文件 +X/-Y，点击开展行级 diff），
  挂在每个 ChatRun 内；useTaskStream 的 RunState 加 fileChanges 字段。
- 产物(create)带 after 全文供下载；改动(patch)不带全文（diff 已够展示，控制 snapshot 体积）。

## 验证
- 前端 17 passed（新增 file-changes.test.tsx 4 项）；全量 Python 265 passed + 1 skipped
- 端到端（真实 runtime）：项目会话写 2 文件 + 改 1 文件 → snapshot 显示
  artifacts=2 / changes=1（readme.txt +1/-1）→ 文件真实落盘
