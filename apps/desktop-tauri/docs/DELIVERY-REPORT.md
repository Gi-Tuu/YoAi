# Tauri 桌面客户端迁移 · 交付报告（2026-11-24）

> 任务：在 **YoAi**（用户拍板的工作区）建 Tauri 2 + React + TS 下一代桌面端，
> 复用 Python Agent Runtime 与 YAI Agent Core，旧 PySide6 保留。
> **未执行任何远程 push/发布**（任务要求）。

## 一、完成内容

### P0（最高优先级）—— 已交付且真实跑通

1. **仓库/调用链盘点**（阶段 A）：核对 `src/yoai/desktop/{app,worker,main_window}.py`
   与 `YoAiAgent.astream` 的真实链路；功能对应清单见 `FEATURE-MAPPING.md`。
2. **Tauri 2 工程骨架**（阶段 B）：`apps/desktop-tauri/` 独立目录，
   React + TS 严格模式（含 noUncheckedIndexedAccess）+ Vite + 设计令牌 +
   Windows 构建配置（msi/nsis）+ 托盘 + 生命周期。
3. **Python Desktop Runtime**（阶段 C）：版本化 JSONL IPC（`docs/IPC-PROTOCOL.md`），
   命令/状态/事件/final/审批结构化；task_id/run_id 隔离 + seq 去重 + 取消 +
   异常恢复；复用 Core 公开 `SidecarChannel` 处理审批/澄清；**内核零改动**。
   - **真实端到端验证**：任务 "1+1等于几" → `status(running)` → 50 条事件 →
     `final("2")` → `status(done)`，seq 严格递增。
4. **过程虚拟化 + 增量更新**（阶段 E）：TanStack Virtual，默认折叠，
   实时区与历史分离；10,000 事件 DOM 行恒为 3。
5. **主工作台**（阶段 D）：聊天、Markdown（表格/代码高亮/复制）、流式文本、
   工具卡片、专员选择、审批弹窗、任务停止/重跑、悬浮胶囊。

### P1 —— 部分交付

- 系统托盘（显示/退出、左键唤出）：已实现
- 思考默认折叠 + 查看入口：已实现
- 设置页 / 会话页：命令协议已定义，UI 未做
- 悬浮窗拖动 + 位置记忆 + 多显示器/DPI：胶囊形态有，这些细节未做

## 二、新增 / 调整的主要文件

| 路径 | 内容 |
|---|---|
| `apps/desktop-tauri/package.json` / `vite.config.ts` / `tsconfig.json` | 前端工程配置（严格 TS） |
| `apps/desktop-tauri/src/App.tsx` | 主工作台入口 |
| `apps/desktop-tauri/src/components/{ProcessPanel,Markdown}.tsx` | 虚拟化过程面板、Markdown 渲染 |
| `apps/desktop-tauri/src/hooks/useTaskStream.ts` | 增量状态、seq 去重、流式累积、跟随底部 |
| `apps/desktop-tauri/src/lib/ipc.ts` | IPC 客户端（rAF 批量、去重） |
| `apps/desktop-tauri/src/types/ipc.ts` | 协议 TypeScript 类型 |
| `apps/desktop-tauri/src/styles/{tokens,app}.css` | 设计令牌 + 样式（尊重减少动效） |
| `apps/desktop-tauri/runtime/{yoai_runtime,protocol,yai_core_sidecar_channel}.py` | Python IPC runtime |
| `apps/desktop-tauri/src-tauri/{Cargo.toml,build.rs,tauri.conf.json,src/*.rs,capabilities/*}` | Rust 宿主 / IPC 桥 / 托盘 |
| `apps/desktop-tauri/scripts/{dev,build-windows}.mjs` | 开发启动 / Windows 构建 |
| `apps/desktop-tauri/tests/*` | runtime 5 项 / 前端 3 项 / 性能基准 5 项 |
| `apps/desktop-tauri/docs/*.md` | IPC 协议 / 功能对应 / Windows 构建 / 性能 / 本报告 |

**旧端 `src/yoai/desktop/**` 与内核零改动**（`git status` 可见新目录独立）。

## 三、验证结果（真跑）

| 验证 | 结果 |
|---|---|
| YoAi 本体全量 pytest | **288 passed**（新工程未破坏旧端） |
| Runtime 协议/取消单测 | **5 passed** |
| 前端 typecheck（strict） | **通过，0 错误** |
| 前端单测 | **3 passed** |
| 性能基准 | **5 passed** |
| Runtime 真握手 | `ready` + 26 个真实工具（含 shell_run/open_url） |
| Runtime 真任务 | "1+1" → final "2" → done，事件 seq 0..51 完整 |
| Tauri 原生构建 | 🟡 Rust 已装（镜像 77s）、crate 已配镜像下载；**卡在 MSVC 链接器**：系统无 VS Build Tools，且 Git Bash 的 GNU `link.exe` 抢占名字（`link: extra operand`）。VS Build Tools 安装中，装完需重编 |

## 四、性能对照（jsdom 前端层实测）

| 事件数 | 折叠渲染耗时 | DOM 行数 |
|---|---|---|
| 50 | 12.8 ms | 3 |
| 200 | 1.6 ms | 3 |
| 1,000 | 1.3 ms | 3 |
| 10,000 | 2.2 ms | 3 |

目标「200 条展开 100ms 内响应」在前端渲染层满足；真实窗口指标待 Rust 构建完成后补测。

## 五、剩余问题（诚实标注）

1. **MSVC 链接器缺失**：Rust + crate 镜像已解决（rustc 1.100 装好、478 包下载完成），
   但 Windows MSVC 工具链（VS Build Tools）未装，且 Git Bash 的 GNU `link.exe`
   抢占 PATH 导致 `link: extra operand`。VS Build Tools 后台安装中。
   **Tauri 原生编译/端到端未实测**——这是环境依赖，不是 Rust 代码问题
   （前端 tsc/build 已过，Rust 代码待 MSVC 就绪后验证）。
2. **嵌入式 Python 未准备**：正式包需把 CPython + yoai/yai_core 放进
   `src-tauri/resources/`（步骤见 `WINDOWS-BUILD.md`），当前未做。
3. **设置页/会话页 UI**、**悬浮拖动/位置记忆/DPI**：未实现（功能对应表标 🟡/⏳）。
4. **性能真机指标**（首次交互时间/内存/CPU）：无 Tauri 运行环境，未测。
5. **代码签名**：未做（正式分发需要 EV 证书）。

## 六、迁移与回退

- 新端在 `apps/desktop-tauri/`，旧端 `src/yoai/desktop/` 完全保留；
- 回退：直接用旧启动方式（`python -m yoai.desktop` 或旧 exe）即可；
- 内核 `YoAiAgent`/Core 未改，任何一端都能连同一套 runtime 语义。
