# 终端与浏览器基础能力（2026-11-24）

此前 YoAi 没有终端工具，也没有内置浏览器（聊天视图是 `QTextBrowser` 富文本，
不是网页渲染；spec 明确排除 `PySide6.QtWebEngineCore`）。本轮按"轻量、不增重、
不碰用户正在编辑的 UI 文件"的口径落地两项基础能力。

## shell_run：受限终端工具

**不是 shell，是一条受限命令执行器**：

| 边界 | 实现 |
|---|---|
| 无 shell 解释 | `subprocess.run(shell=False)` + `shlex` 分词；管道 `\|`、重定向 `>`、`&&` 只是普通 argv 参数，不会生效 |
| 工作目录 | 固定在宿主分配的 workspace 根（模型无法 `cd` 出去；`..` 路径参数仍可能被命令自身接受，审批时可见全文） |
| 凭据保护 | 子进程环境剔除含 `KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL/AUTH/COOKIE` 等字样的变量——模型执行 `env` 也拿不到网关 key |
| 超时 | 1-60 秒，默认 15 秒；超时如实返回，不留孤儿等待 |
| 输出 | 截断上限 8000 字符（可调 500-30000），返回 `ok/exit_code/output/truncated` JSON |
| **权限** | **不进 auto 白名单**——桌面 auto 档每次弹窗确认，默认拒绝；关窗一律拒绝 |

**不支持**交互式程序、`cd` 后连续执行、管道/重定向。需要复杂流水线时请拆成多条命令。

## open_url：系统浏览器工具

- 仅接受 `http://` / `https://`，拒绝 `file://` 等协议（防本地文件探测）；
- 用系统默认浏览器打开（`webbrowser.open`，新标签）；
- 进入 auto 白名单（与 `web_search`/`web_fetch` 同类，轻量只读）；
- 适合让用户亲自看富内容；纯文本阅读仍用 `web_fetch` 更省。

## 关于"内置浏览器"

本轮**不做** QWebEngine 内置面板：①会显著增大 exe 并引入打包复杂度；
②用户正在编辑 `main_window.py` / `widgets.py`，按规矩不触碰。
如后续需要真·内置面板，可在 UI 编辑收尾后单独做（建议独立窗口，不动主界面代码）。

## 实现位置

- `src/yoai/tools_shell.py`：两个工具 + 4 项安全边界（纯标准库）
- `src/yoai/tools_builtin.py`：`builtin_tool_specs` 汇入（随 `builtin_tools` 开关启用）
- `src/yoai/desktop/app.py`：auto 白名单只加 `open_url`，`shell_run` 留空走审批
- `yoai.spec`：补 `yoai.tools_shell` hiddenimports（函数内延迟导入）

## 测试

`tests/test_shell_browser.py` 9 项：workspace cwd、无 shell 解释、超时、输出截断、
凭据环境变量过滤、坏命令报错、URL 协议校验、builtin 注册、权限白名单分离。
全量 **266 passed**。
