"""受限终端 + 系统浏览器工具（2026-11-24）。

设计原则：
- **终端不是 shell**：shell=False + shlex 分词，没有管道/重定向/命令链；
  工作目录固定在 workspace 根内，超时、输出截断、剔除敏感环境变量。
- **审批是安全边界**：shell_run 不进桌面 auto 白名单，每次调用弹窗确认
  （默认拒绝）；open_url 只允许 http/https，用系统默认浏览器打开。
- 两者都是纯 Python 标准库实现，内核零改动、exe 不增重。

返回 ToolSpec 列表，由 builtin_tool_specs 汇入 YoAiAgent 注册表。
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

from yai_core import build_spec

# 环境变量白名单剔除规则：凭据类变量一律不传给子进程
# （否则模型只要执行 `env` 就能拿到网关 key）
_SENSITIVE_ENV = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|SIGNATURE|COOKIE)",
    re.IGNORECASE,
)


def _split_command(command: str) -> list[str]:
    """把命令字符串切成 argv（无 shell 解释）。

    Windows 下 shlex(posix=False) 会保留外层引号，手工剥掉；
    POSIX 下按标准 shlex 处理。管道/重定向符号只会变成普通参数，不生效。
    """
    if os.name == "nt":
        parts = shlex.split(command, posix=False)
        return [
            p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p
            for p in parts
        ]
    return shlex.split(command, posix=True)


def shell_tool_specs(root: str | Path) -> list[Any]:
    """构建受限终端工具 spec。root 固定为命令的工作目录。"""
    cwd = str(Path(root).resolve())

    def shell_run(command: str, timeout: int = 15, max_chars: int = 8000) -> str:
        """在工作目录内执行一条命令并返回输出（受限，无 shell）。

        command 是可执行文件 + 参数（如 `python script.py --flag`），
        **不支持**管道 |、重定向 >、&& 等 shell 语法——它们只会被当普通参数。
        timeout 秒数（1-60，默认15）；max_chars 限制返回长度（500-30000）。

        工作目录固定在宿主允许的 workspace 内，无法 cd 出去；凭据类环境变量
        （KEY/TOKEN/SECRET/PASSWORD 等）已从子进程环境中剔除。
        本工具需要审批确认；执行结果如实返回，未执行/失败会写明原因。
        """
        import json

        timeout = max(1, min(60, int(timeout)))
        max_chars = max(500, min(30000, int(max_chars)))
        try:
            argv = _split_command(command)
        except ValueError as exc:
            return json.dumps({"ok": False, "error": f"命令解析失败：{exc}"},
                              ensure_ascii=False)
        if not argv:
            return json.dumps({"ok": False, "error": "命令为空"}, ensure_ascii=False)
        env = {k: v for k, v in os.environ.items() if not _SENSITIVE_ENV.search(k)}
        try:
            proc = subprocess.run(
                argv, cwd=cwd, shell=False, env=env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": f"命令超时（{timeout}秒）"},
                              ensure_ascii=False)
        except (OSError, ValueError) as exc:
            return json.dumps({"ok": False, "error": f"执行失败：{type(exc).__name__}: {exc}"},
                              ensure_ascii=False)
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        truncated = len(out) > max_chars
        return json.dumps({
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": out[:max_chars],
            "truncated": truncated,
        }, ensure_ascii=False)

    return [build_spec(shell_run)]


def open_url(url: str) -> str:
    """用系统默认浏览器打开一个网页（仅 http/https）。

    适合让用户亲自查看网页/视频/地图等富内容；纯文本阅读用 web_fetch 更省。
    """
    lower = url.strip().lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        return "仅支持 http/https 地址（不允许本地文件或其它协议）"
    try:
        ok = webbrowser.open(url, new=2)
    except Exception as exc:  # noqa: BLE001
        return f"打开失败：{type(exc).__name__}: {exc}"
    return (f"已请求系统默认浏览器打开：{url}" if ok
            else "系统未能打开浏览器（可改用 web_fetch 读取正文）")


def browser_tool_specs() -> list[Any]:
    """构建系统浏览器工具 spec。"""
    return [build_spec(open_url)]
