"""受限终端 + 系统浏览器工具测试（2026-11-24）。

- shell_run：无 shell 解释、cwd 限 workspace、超时、输出截断、剔除凭据环境变量；
- open_url：仅 http/https，调系统默认浏览器；
- 注册与权限：两个工具在 builtin 表里；shell_run 不进 auto 白名单、open_url 进。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.tools_shell import browser_tool_specs, shell_tool_specs  # noqa: E402
from yoai.tools_builtin import builtin_tool_specs  # noqa: E402


def _shell(tmp_path: Path):
    specs = {s.name: s for s in shell_tool_specs(tmp_path)}
    return specs["shell_run"].handler


def test_shell_runs_command_in_workspace(tmp_path):
    handler = _shell(tmp_path)
    result = json.loads(handler(f'{sys.executable} -c "import os; print(os.getcwd())"'))
    assert result["ok"] is True
    assert tmp_path.name in result["output"]


def test_shell_no_shell_interpretation(tmp_path):
    """管道/&& 只是普通 argv 参数，不会启动第二个命令。"""
    handler = _shell(tmp_path)
    result = json.loads(
        handler(f'{sys.executable} -c "import sys; print(sys.argv[1:])" FIRST && echo SECOND',
                timeout=5)
    )
    assert result["ok"] is True
    # && 被原样当成 argv 的一项，不是 shell 运算符
    assert "'&&'" in result["output"] and "'FIRST'" in result["output"]


def test_shell_timeout(tmp_path):
    handler = _shell(tmp_path)
    result = json.loads(
        handler(f'{sys.executable} -c "import time; time.sleep(5)"', timeout=1)
    )
    assert result["ok"] is False
    assert "超时" in result["error"]


def test_shell_truncates_output(tmp_path):
    handler = _shell(tmp_path)
    result = json.loads(
        handler(f'{sys.executable} -c "print(\'x\'*4000)"', max_chars=500)
    )
    assert result["truncated"] is True
    assert len(result["output"]) == 500


def test_shell_filters_credential_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YOAI_TEST_SECRET_TOKEN", "should-not-leak")
    handler = _shell(tmp_path)
    result = json.loads(
        handler(f'{sys.executable} -c "import os; print(os.environ.get(\'YOAI_TEST_SECRET_TOKEN\'))"')
    )
    assert result["ok"] is True
    assert "should-not-leak" not in result["output"]
    assert "None" in result["output"]


def test_shell_bad_command_reports_error(tmp_path):
    handler = _shell(tmp_path)
    result = json.loads(handler("definitely_not_a_real_command_xyz", timeout=5))
    assert result["ok"] is False
    assert "执行失败" in result["error"]


def test_open_url_valid_and_invalid(monkeypatch):
    import yoai.tools_shell as ts

    seen = []
    monkeypatch.setattr(ts.webbrowser, "open", lambda url, new: seen.append(url) or True)
    handler = browser_tool_specs()[0].handler

    assert "已请求" in handler("https://example.com/path")
    assert seen == ["https://example.com/path"]
    assert "仅支持" in handler("file:///C:/Windows/win.ini")
    assert len(seen) == 1   # 非法 URL 不打开


def test_builtin_registers_both(tmp_path):
    names = {s.name for s in builtin_tool_specs(tmp_path)}
    assert {"shell_run", "open_url"}.issubset(names)


def test_permission_whitelist_split():
    """shell_run 必须走审批；open_url 在 auto 白名单。"""
    import ast

    src = (ROOT / "src/yoai/desktop/app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "readonly_and_internal":
                    allowed = {e.value for e in node.value.elts}
    assert allowed is not None
    assert "open_url" in allowed
    assert "shell_run" not in allowed
