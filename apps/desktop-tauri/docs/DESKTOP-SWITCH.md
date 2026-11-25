# 桌面默认 UI 切换说明（2026-11-25）

## 现状

| 项 | 位置 | 说明 |
|---|---|---|
| **当前默认（新 Tauri）** | `dist/YoAi.exe` | Tauri 2 + React UI，功能已对齐旧端（会话管理/侧栏/通讯/星球系/主题） |
| 回退（旧 PySide6） | `dist/YoAi-PySide6.exe` | 60MB，旧端**最后产物**（源码已删，仅存此 exe 作回退） |
| 数据目录 | `dist/output/` | runtime 自举识别 dist 布局，**沿用旧端会话/记忆**（2 会话 62 条历史已验证） |
| 单实例 | tauri-plugin-single-instance | 第二实例唤前台主窗（对齐旧端语义） |
| 桌面快捷方式 | `~/Desktop/YoAi.lnk` | **未改动**，仍指向 `dist/YoAi.exe`（现在内容是新端） |
| Python runtime | `dist/runtime/*.py` | 新 exe 启动时 spawn 的桥接层 |

## 切换做了什么

1. 旧 exe 备份：`dist/YoAi.exe` → `dist/YoAi-PySide6.exe`
2. 新 exe：`apps/desktop-tauri/src-tauri/target/release/yoai-desktop-tauri.exe` → `dist/YoAi.exe`
3. runtime 脚本复制到 `dist/runtime/`（3 个 py），并让自举逻辑兼容 dist 位置
4. 设用户级持久环境变量（exe 依赖它找 Python）：
   - `YOAI_PYTHON` = 含 yoai + yai_core 的 venv python.exe
   - `YAI_CORE_SRC` = YAI Agent Core 的 src 目录

## 回退方法（随时可切回旧端）

**方法 A（快捷方式改回旧端）**：把桌面 `YoAi.lnk` 的目标改成
`dist/YoAi-PySide6.exe` 即可。

**方法 B（文件替换）**：
```bash
cd <YOAI_ROOT>/dist
cp YoAi-PySide6.exe YoAi.exe     # 覆盖回旧端（先另存新的）
```
想再切回新端：从 `apps/desktop-tauri/src-tauri/target/release/` 复制 exe 过来。

**注意**：旧端（PySide6）不需要 `YOAI_PYTHON`/`YAI_CORE_SRC` 环境变量，
这两个变量只影响新端；保留它们对旧端无害。

## 启动链路（新端）

```
双击 YoAi.lnk → dist/YoAi.exe (Tauri)
  → Rust 读 resource_dir()/runtime/yoai_runtime.py（= dist/runtime/）
  → 用 YOAI_PYTHON 启动 Python 子进程
  → hello 握手 → ready(26 工具) → task.start → 事件流 JSONL → React 上屏
```

## 验证（真跑）

- exe 启动会 spawn Python 子进程（实测进程出现）
- dist 里的 runtime 从 dist 位置握手成功（26 个真实工具）
- dist 里的 runtime 真任务："3×7" → `final("21")` → `done`
- 旧端 exe 备份存在（60MB），可随时回退

## 未验证 / 注意

- **GUI 窗口目视未验证**：环境安全策略禁止启动 GUI 进程，只能验证到进程链路层。
  双击后若有显示问题，看 stderr 或用 `dist/YoAi.exe` 命令行启动观察。
- 新端 UI 的功能完整度见 `FEATURE-MAPPING.md`（设置页/会话页/拖动/DPI 未做）。
- 打包成 MSI 分发到其他机器仍需嵌入式 Python（见 `WINDOWS-BUILD.md`）；
  本机已用持久环境变量解决。

## 对话页锚点交互（2026-11-25 14:20）

右侧信息栏从常驻三卡改成**边缘小方块锚点**：事实「事」/目标「志」/记忆「忆」，
带数量角标。悬停以自身为中心展开 DOM popover（140ms 生长动画），落点按与对话区/
窗口边缘的距离自适应（computeAnchorPosition 纯函数，jsdom 可测）；指针在方块与
卡片间移动不误关，移开 140ms 收回。

**点击「◱ 钉住」转 Tauri 原生浮窗**：无边框/透明/置顶/可拖动缩放，能浮到桌面任意位置。
主窗口 snapshot 变化时通过 `push_float_data` emit 给已钉住的浮窗；浮窗加载
`index.html?float=<kind>`，在入口层分流，只渲染不连 runtime（避免第二个 IPC 客户端
发 hello 污染任务流）。

**关键修复**：`on_window_event` 的 runtime shutdown 限定 main 窗口——否则关浮窗会把
Python 子进程杀掉。

测试：前端 16 passed（新增 anchor-rail.test.tsx 6 项：几何自适应/hover/钉住）、
全量 Python 256 passed；Rust 编译通过。

## 悬停直接出原生窗 + 推理模型超时修复（2026-11-25 15:25）

**按所有者要求改为悬停直接出原生窗**（替代上一版"悬停 DOM + 点击钉住"）：
- 悬停方块 → Rust `hover_float_panel` 创建/定位无边框置顶浮窗到锚点旁，能浮出桌面
- 跨窗口 hover 协调：主窗/浮窗都 emit `float://hover-signal`，浮窗侧维护
  anchor/panel 进入状态，都离开 250ms 后自动收起；点击内容区钉住不再收起
- **风险（待真机验收）**：浮窗置顶会遮挡主窗，鼠标移向浮窗路径可能误触发 leave；
  250ms 延迟缓解但未在 GUI 实测
- 浮窗 listener 用静态 import（动态 import 绕过 mock，且生产可能丢 float://data）

**60s 超时修复**（用户截图 TimeoutError）：Core `AgentLoop` 默认 `model_timeout=60s`，
spark-x2.6 带 26 工具 schema 首 token 可达 40s+，升档纠偏轮叠加就破 60s。
YoAi 构造 AgentCore 时传 `model_timeout`（默认 180s，`YOAI_MODEL_TIMEOUT` 可覆盖，
0=禁用），内核零改动。回归测试覆盖默认值/禁用/覆盖/非法回退。

会话 `977a2f22` 两条"无法查看目录"失败叙事已备份后清洗（能力已具备但历史污染）。

## 浮窗白屏 + 只读工具可发现性（2026-11-25 15:45）

**浮窗白屏根因**：`WebviewUrl::App` 只接受路径（PathBuf），不接受查询串。
传 `index.html?float=facts` 会被当成文件名去找 → 白屏。
修复：`WebviewUrl::App("index.html")` + `initialization_script` 注入
`window.__FLOAT_KIND__`，main.tsx 读全局变量分流。

**模型仍说"能力缺失"根因**（用户 15:37 贴的回复）：能力有（file_ro_list/file_ro_read
已注册 28 工具），但模型只用 file_list（沙箱）试 E 盘路径、从没意识到有只读挂载工具。
属可发现性问题。修复：file_ro_* 描述写明"访问宿主机真实磁盘必须用本工具 + path 怎么写"；
并在 file_list/file_read/shell_run 描述追加提示引导改用 file_ro_*（YoAi 侧包装 Core spec，
内核零改动）。回归测试 test_readonly_tools_are_discoverable。
全量 258 passed。
