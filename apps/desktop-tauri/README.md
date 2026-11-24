# YoAi 下一代桌面客户端（Tauri 2 + React + TS）

> 独立新工程，旧 PySide6 桌面端（`src/yoai/desktop/`）**保留不动**，作为迁移期回退方案。
> Python 内核零改动：runtime 只消费 `YoAiAgent.astream()` 的真实事件流。

## 目录

```
apps/desktop-tauri/
├── src/                    React 前端（工作台/过程面板/悬浮胶囊/Markdown）
├── src-tauri/              Rust 宿主（启动 Python 子进程、JSONL IPC、托盘、生命周期）
├── runtime/                Python IPC runtime（命令→astream→JSONL 事件）
├── tests/                  前端单测 + 性能基准 + runtime 协议测试
├── docs/                   IPC 协议 / 功能对应 / Windows 构建 / 性能记录
└── scripts/                开发启动 + Windows 构建
```

## 快速验证（不依赖 Rust 编译）

```bash
# 1. Python runtime 测试（真 agent 构造 + 事件翻译，mock 任务）
python -m pytest tests/test_runtime_protocol.py -q

# 2. 前端类型检查 + 单测
npm install
npm run typecheck
npm test

# 3. 性能基准
npx vitest run tests/perf.bench.test.ts

# 4. Runtime 真实握手（不需要 Tauri）
echo '{"v":1,"type":"hello","client":"test","protocol":1}' | python runtime/yoai_runtime.py
```

## 启动桌面端（需 Rust 工具链）

```bash
set YOAI_PYTHON=<含 yoai 与 yai_core 的 python.exe>
set YAI_CORE_SRC=<Core/src 路径>
node scripts/dev.mjs
```

## 当前状态（诚实）

- ✅ P0：真实 Agent 任务经 IPC 跑通（`status`→事件流→`final`→`done`，实测 "1+1" 返回 "2"）
- ✅ P0：过程面板虚拟化（10,000 事件 DOM 行恒为 3，渲染 2.2ms）
- ✅ P0/P1：主工作台、Markdown、工具卡片、审批弹窗、悬浮胶囊、托盘
- 🟡 Rust 原生构建：环境 Rust 工具链下载中（网络慢），**Tauri 端到端尚未实测**
- ⏳ 设置页、会话页、多显示器/DPI、嵌入式 Python 打包（详见 `docs/FEATURE-MAPPING.md` / `WINDOWS-BUILD.md`）

详细文档：`docs/IPC-PROTOCOL.md`、`docs/FEATURE-MAPPING.md`、
`docs/WINDOWS-BUILD.md`、`docs/PERFORMANCE.md`。
