# Windows 开发与构建说明

## 1. 环境

| 依赖 | 版本 | 用途 |
|---|---|---|
| Node.js | 22.x（实测 22.22.2） | 前端构建 |
| Rust（rustup） | stable + MSVC toolchain | Tauri 原生编译 |
| Python | 3.13（实测 3.13.15） | YoAi Runtime（开发模式） |
| YoAi 源码 | `$YOAI_ROOT`（本机工程根） | `yoai` 包 + Core 通过 PYTHONPATH 引用 |

Rust 安装：`https://rustup.rs`（Windows 选 MSVC toolchain）。
验证：`cargo --version` 应有版本号；若报 "error reading rustc version"，
执行 `rustup toolchain uninstall stable-x86_64-pc-windows-msvc` 再
`rustup toolchain install stable-x86_64-pc-windows-msvc --profile minimal`。

## 2. 开发模式

```bash
# 设 Python（含 yoai 与 yai_core 的 venv）
set YOAI_PYTHON=<含 yoai 与 yai_core 的 python.exe 绝对路径>
set YAI_CORE_SRC=<YAI Agent Core 的 src 目录绝对路径>

cd apps/desktop-tauri
npm install
node scripts/dev.mjs
```

`dev.mjs` 先检查 Node/Rust/Python 环境，再启动 `tauri dev`（Vite 1420 端口）。
Tauri 会拉起 Python runtime 子进程，握手 `hello`/`ready` 后即可发任务。

## 3. Windows 正式打包（未装 Python 的机器）

**关键**：正式包必须自带 Python，否则目标机器跑不起来。

1. 准备嵌入式 Python：把 CPython 3.13 的 `python.exe` + `Lib` + `DLLs` +
   依赖的 `yoai` / `yai_core` 源码放到
   `apps/desktop-tauri/src-tauri/resources/python/`。
   推荐用 `python-build-standalone`（免安装、可再分发）避免系统 Python 依赖。
2. 把 runtime 脚本与依赖一起放进 `src-tauri/resources/runtime/`
   （当前 `runtime/yoai_runtime.py` + `protocol.py` + `yai_core_sidecar_channel.py`）。
3. 在 `tauri.conf.json` 的 `bundle.resources` 注册上述目录（当前未注册——
   **打包前必须补**，否则 resources 不进安装包）：
   ```json
   "resources": ["resources/python", "resources/runtime"]
   ```
4. **MSVC 环境（关键，否则 `link: extra operand`）**：Windows 上 Git Bash 自带 GNU
   `link.exe`（coreutils），会抢占 PATH 让 rustc 调错链接器。必须用 PowerShell 先注入
   VC 环境：
   ```powershell
   cd apps/desktop-tauri
   .\scripts\build-env.ps1 -Build     # 注入 vcvars64 + 直接构建
   # 或只设环境：.\scripts\build-env.ps1，然后在同一会话跑 npm run tauri build
   ```
   前提：已装 **VS Build Tools + C++ 构建工具 workload**（`winget install
   Microsoft.VisualStudio.2022.BuildTools --override "--wait --quiet --add
   Microsoft.VisualStudio.Workload.VCTools --includeRecommended"`）。
   脚本会验证 `link.exe` 确实来自 Visual Studio，否则直接报错。

5. 构建（仅当已在正确的 MSVC 环境里）：
   ```bash
   cd apps/desktop-tauri
   npm run build
   npm run tauri build
   # 或：node scripts/build-windows.mjs（不注入 MSVC 环境，需先跑 build-env.ps1）
   ```
6. 产物：`src-tauri/target/release/bundle/msi/` 与 `nsis/`。

`scripts/build-windows.mjs` 会检查嵌入式 Python 是否存在并给出警告，避免
静默产出跑不起来的安装包。

## 4. 运行时路径管理

| 场景 | Python 解释器 | runtime 脚本 |
|---|---|---|
| 开发（`tauri dev`） | `YOAI_PYTHON` 环境变量，缺省 `python` | 工程内 `runtime/yoai_runtime.py` |
| 打包 | `resources/python/python.exe` | `resources/runtime/yoai_runtime.py` |

Rust `runtime_paths()` 自动判定：资源目录有内置版本就用内置，否则回退开发环境。

## 5. 错误提示与退出清理

- 启动失败（Python 缺失/脚本不存在）→ Rust emit `type:error,stage:startup` → React 顶部错误条
- runtime stdout 非法 JSON → `type:error,stage:protocol`（stdout 被污染时可见）
- 窗口销毁 → 发 `shutdown` 命令 + `child.kill()/wait()`，避免残留进程
- 托盘“退出” → `app.exit(0)` → 触发同样的清理路径

## 6. 未完成项（诚实标注）

- **嵌入式 Python 未准备**：当前安装包只能在预装 Python 的机器运行（已在上文说明步骤）
- `bundle.resources` 尚未注册（见第 3 节第 3 步），打包前必须补
- 未做代码签名（正式分发需要 EV 证书）
- 多显示器/DPI 缩放未显式处理
