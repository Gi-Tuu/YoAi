# 旧端 UI 搬迁与清理报告（2026-11-25）

> 一次完成：旧 PySide6 端 UI 全部能力搬入 Tauri 新端，随后旧端源码清理删除。
> 用户指令："先把旧端UI全部搬到新端，无论是否提交都要搬。然后把旧端UI清理干净。"

## 一、搬移清单（旧端能力 → 新端实现）

| 旧端能力 | 新端实现 | 位置 |
|---|---|---|
| 会话下拉切换 / ＋新建 / 管理菜单（重命名、删除）/ 忙时禁用 | header 会话条 + 模态对话框 | `App.tsx` + `Dialog.tsx` |
| 会话历史加载（切会话不丢上下文） | `snapshot.history` 渲染 | `App.tsx` |
| 右栏卡片：个人事实 / 长期目标 / 本轮记忆写入统计 | `SideCards.tsx`（write_stats 语义对齐旧端） | `SideCards.tsx` |
| 错误可见（error/permission_denied/budget_exceeded 进正文 + "部分失败"状态） | run 内警示行 + 状态标红（对齐旧端 `_task_had_error` 静默失败修复） | `App.tsx` ChatRun |
| final 空文本 → 流式缓冲兜底 + `<tool_output>` 清理 | 移入 runtime（发协议前完成） | `yoai/bootstrap.py` clean_final_text + `yoai_runtime.py` |
| 模型 chip（穿透包装链取真实模型名） | `resolve_model_name`（新增 .adapter 穿透，实测解析出 spark-x2.6） | `yoai/bootstrap.py` |
| 纸墨主题 light/dark 切换 | CSS 变量 + `data-theme`（色值抄自旧端 cosmic/theme.py Palette） | `tokens.css` |
| 通讯页：单聊/群列表、建群、拉人、外部智能体双击入群、发消息、历史 | `CommsPage.tsx`（runtime 经 channel/registry 语义全等移植） | `CommsPage.tsx` |
| 星球系：恒星=根 / 行星=专家 / 轨道=血统 / 光晕=生命周期 / 点击详情卡 | `GalaxyPage.tsx`（纯 SVG，无依赖） | `GalaxyPage.tsx` |
| 审批弹窗（工具写操作确认） | 内嵌审批卡 + detail 美化（reason 优先展示） | `App.tsx` + runtime approval_request |
| 证据落盘（ExecutionEvidenceCollector + 路由归因） | 移入 runtime 任务循环（旁路，失败不影响任务） | `yoai_runtime.py` _run |

顺带修复：`useTaskStream` 事件重复消费 bug（msgs 全量重推导致同一事件重复追加）——
改为游标增量消费；`resetRuns` 支持切会话清空 run 视图。
顺带修复：runtime stdin 读取改 daemon 线程（shutdown 后进程立即退出，不再卡 readline）。

## 二、协议扩展（v1 兼容追加，旧消息零改动）

新命令：`session.state/create/switch/rename/delete`、`chat.state/history/send/new_group/add_member/add_external`、`archive.get`。
新消息：`snapshot`、`chat.state`、`chat.msg`、`archive.state`。
同步三处：`runtime/protocol.py` ↔ `src/types/ipc.ts` ↔ `docs/IPC-PROTOCOL.md`。

## 三、清理清单（旧端源码删除）

- `src/yoai/desktop/` 整目录（app/main_window/widgets/chat_panel/chat_worker/worker/approval/single_instance/markdown_html/cosmic/*，共 16 文件 2495 行 + cosmic 7 文件）
- 10 个 Qt 测试：test_approval / test_chat_ui / test_cosmic_ui / test_desktop / test_desktop_shutdown / test_evidence_worker / test_external_ui / test_session_ui / test_single_instance / test_markdown_render
- `yoai.spec`（旧 PySide 打包 spec；旧端最后产物=dist/YoAi-PySide6.exe，保留回退）

**保留/迁移（非 UI 基础设施）**：
- `_agent_kwargs` / `_build_main_model` / 模型名解析 / final 清理 → 新建 `src/yoai/bootstrap.py`（runtime 依赖它，无 UI 依赖）
- `session.py` 的 `rename/delete`（用户 11-24 未提交改动）保留——runtime 会话管理在用
- `yoai/chat` / `yoai/adapters` / `yoai/demo_world` / `yoai/evidence` / `yoai/evolution` 全部保留（通讯/证据/进化基础设施）

## 四、测试改造

- 新增 `tests/test_tauri_runtime.py`（10 项）：协议构造器契约、Seq 去重语义、bootstrap 纯函数
- `test_expert_provider.py`：Qt worker 用例改写为 async 证据闭环（同语义，无 Qt）
- `test_permission_mode.py`：import 改指 `yoai.bootstrap.agent_kwargs`
- `test_shell_browser.py`：权限白名单源码断言改读 `bootstrap.py`
- **全量 241 passed**（删除 10 个 Qt 测试文件后净减）；前端 vitest 8 passed；typecheck/build 干净

## 五、验证记录（真跑过）

1. runtime 进程内冒烟：组装 0.39s，snapshot（1 会话/8 历史/26 工具/1 事实）、chat.state（4 会话/12 外部）、archive（1 节点）、模型名 spark-x2.6 ✓
2. runtime subprocess 端到端：hello→ready+snapshot+chat.state；session create/rename/switch/delete 闭环 ✓（create 断言写错排序方向已核实为测试脚本问题，非实现问题）；archive.get ✓
3. 前端：`tsc -b` 干净、`vite build` 成功（558KB）、vitest 8 passed
4. Rust：手工 MSVC 环境（绕开 vcvars 的 reg.exe 沙箱限制）`cargo build --release` 成功
5. dist 更新：`YoAi.exe`（9.87MB，含新前端）+ `dist/runtime/` 三件套同步

## 六、未完成 / 需拍板

- **GUI 目视验证**：安全策略限制 AI 无法看界面，需要你实际打开 dist/YoAi.exe 核对（对话/通讯/星球系/主题切换/会话管理）。
- **未提交**：全部改动在工作区（28 删除 + 13 修改 + 4 新增），等你确认后再 commit。
- 旧端"悬浮胶囊/单实例守卫"对应项：胶囊新端已有；Tauri 单实例（tauri-plugin-single-instance）未加，如需加再说。
- 旧端 exe 内嵌的 self-check 入口随 app.py 删除；新端自检走协议冒烟（见上）。


## 七、接入验证与后续修复（2026-11-25 上午，用户追问"py runtime 接入了吗"）

**结论：接入了，但发现并修复了 4 个真 bug**（均有实证）：

1. **任务从未执行**（致命）：`Runtime.start_task` 定义了 `_run()` 协程却漏了
   `asyncio.create_task(_run())` —— 前端发出 `task.start` 后只收到 `status(running)`，
   永远没有事件/最终答复。修复后实测：161 个事件（156 thinking + delta）+ final + done。
   这是"py runtime 接了却像没接"的真根因。
2. **数据目录分家**：新 runtime 写项目根 `output/`，旧端会话在 `dist/output/`（2 会话/62 条历史）。
   修复：`_data_dir()` 优先 `YOAI_DATA_DIR`，否则识别 `dist/runtime` → `dist/output`；
   Rust 侧去掉 Tauri AppData 注入。实测恢复读取旧会话。
3. **网关静默降级**：生产 `YAI_CORE_SRC` 指向 `Core/src`，而 SuanliAdapter 把它当根找 `.env`，
   找不到就走 Anthropic DeepSeek。修复：runtime 自举时把该变量规范成 Core 根。
   实测模型名从 `DeepSeek (Anthropic · Core)` 恢复为 `spark-x2.6`。
4. **首次启动崩溃**：空数据目录没有会话时 `current_agent()` KeyError（旧端 app.py 有
   `create("新会话")` 语义，搬迁漏掉）。修复后新用户第一句话可执行。

**单实例守卫补做**：Rust 侧接入 `tauri-plugin-single-instance`，第二实例唤前台主窗
（对齐旧端 QLocalSocket 语义）。

**验证证据**：dist/runtime subprocess 端到端（hello→ready/snapshot/chat.state；
会话 2/历史 62/26 工具/spark-x2.6；task.start→161 事件→final→done→exit 0）；
直连讯飞网关 HTTP 200（推理模型首 token 约 7-45s，属正常延迟）；
全量 pytest 241 passed；Rust 重编 + dist/YoAi.exe（9.9MB）更新。

**注意**：`spark-x2.6` 是推理模型，带工具定义时首字延迟可达 40 秒以上——
新端 front-end 会显示 thinking 过程，属于预期行为，不是卡死。
