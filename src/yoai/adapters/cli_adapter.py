"""L2 CLI 适配器 — 通过非交互子进程真接入智能体。

实测可用：claude -p（返回真实回答）；opencode run（接口正确，本机模型/网络未就绪）。
安全：命令模板来自宿主配置；消息作为参数传入（不在 shell 里拼接），避免注入；
带超时；失败返回 AdapterResult(ok=False)，不抛异常。
"""

from __future__ import annotations

import shlex
import subprocess
from typing import Any

from yoai.adapters.base import AdapterResult, PeerAdapter


class CliAgentAdapter(PeerAdapter):
    """把支持"传 prompt 拿 stdout"的 CLI 包装成 L2 peer。

    command_template 用 {message} 占位，例如：
        ["claude", "-p", "{message}"]
        ["opencode", "run", "--format", "json", "{message}"]
    """

    level = "L2"

    def __init__(
        self,
        name: str,
        command_template: list[str],
        *,
        enabled: bool = True,
        timeout_s: float = 60.0,
        cwd: str | None = None,
        json_output: bool = False,
    ) -> None:
        super().__init__(name, enabled=enabled, timeout_s=timeout_s)
        self.command_template = command_template
        self.cwd = cwd
        self.json_output = json_output
        self.last_error = ""

    def available(self) -> bool:
        if not self.enabled or not self.command_template:
            return False
        exe = self.command_template[0]
        from shutil import which
        return which(exe) is not None

    def capabilities(self) -> list[str]:
        return ["chat", "non_interactive", "auto_reply"]

    def _build_argv(self, message: str) -> list[str]:
        argv = [arg.replace("{message}", message) for arg in self.command_template]
        # Windows: npm 的 CLI 是 .CMD/.BAT，shell=False 时不会按 PATHEXT 解析，
        # 必须用 shutil.which 给出的绝对路径（含扩展名）才能启动。
        from shutil import which
        resolved = which(argv[0])
        if resolved:
            argv[0] = resolved
        return argv

    def send(self, message: str) -> AdapterResult:
        if not self.enabled:
            return AdapterResult(False, level=self.level, detail="适配器已禁用")
        if not self.available():
            return AdapterResult(False, level=self.level,
                                 detail=f"命令不可用：{self.command_template[0]}")
        argv = self._build_argv(message)
        try:
            proc = subprocess.run(
                argv,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
                stdin=subprocess.DEVNULL,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(False, level=self.level,
                                 detail=f"调用超时（>{self.timeout_s}s）：{self.name}")
        except (OSError, ValueError) as exc:
            return AdapterResult(False, level=self.level,
                                 detail=f"调用失败：{type(exc).__name__}: {exc}")

        self.last_error = proc.stderr.strip()[:500]
        if proc.returncode != 0:
            return AdapterResult(False, level=self.level,
                                 detail=f"退出码 {proc.returncode}：{self.last_error[:200]}")

        text = self._parse_output(proc.stdout)
        if not text:
            return AdapterResult(False, level=self.level,
                                 detail=f"无输出（stderr: {self.last_error[:200]}）")
        return AdapterResult(True, text=text, level=self.level,
                             detail=self.last_error[:120])

    def _parse_output(self, stdout: str) -> str:
        if self.json_output:
            return _extract_json_text(stdout)
        return stdout.strip()


def _extract_json_text(stdout: str) -> str:
    """从 opencode --format json 的输出里抽出文本（容错多种形状）。"""
    import json
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for key in ("text", "content", "output", "message", "result"):
                if key in data and isinstance(data[key], str):
                    return data[key]
        elif isinstance(data, str):
            return data
    return stdout.strip()
