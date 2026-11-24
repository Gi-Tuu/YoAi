# 桌面默认 UI 切换说明（2026-11-25）

## 现状

| 项 | 位置 | 说明 |
|---|---|---|
| **当前默认（新 Tauri）** | `dist/YoAi.exe` | 9.8MB，Tauri 2 + React UI |
| 回退（旧 PySide6） | `dist/YoAi-PySide6.exe` | 60MB，原桌面端完整保留 |
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
