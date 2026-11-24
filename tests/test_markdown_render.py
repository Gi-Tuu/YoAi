"""Markdown → HTML 渲染测试（2026-11-24）。

根因：对话视图把内容整体 html.escape 后塞进 HTML，模型返回的 md 语法
（粗体/列表/代码块/链接）全部当纯文本显示。修复：assistant 消息先转义、
再做轻量 md 解析；用户消息仍按纯文本（防输入被当指令渲染）。

覆盖：块级（标题/列表/代码块/水平线）、行内（粗体/斜体/行内码/链接）、
安全（HTML 注入/危险协议）、Qt 集成（ChatView 与 ChatTranscript 真渲染）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.desktop.markdown_html import md_to_html  # noqa: E402


def test_plain_text_unchanged():
    out = md_to_html("你好，世界")
    assert "你好，世界" in out
    assert "<strong>" not in out


def test_bold_italic_inline_code():
    out = md_to_html("**重点** 和 *斜体* 还有 `code()`")
    assert "<strong>重点</strong>" in out
    assert "<em>斜体</em>" in out
    assert "<code" in out and "code()" in out


def test_heading_and_lists():
    out = md_to_html("# 标题\n\n- 第一项\n- 第二项\n\n1. 步骤一\n2. 步骤二")
    assert "标题" in out and "font-weight:600" in out
    assert out.count("<li>") == 4
    assert "<ul" in out and "<ol" in out


def test_fenced_code_block_preserved():
    out = md_to_html("说明：\n\n```python\nprint('**not bold**')\n```\n\n结尾")
    assert "<pre" in out and "print(" in out
    assert "**not bold**" in out   # 代码块内部不解析 markdown


def test_link_only_http_https():
    out = md_to_html("[官网](https://example.com) [危险](file:///C:/x) [脚本](javascript:alert(1))")
    assert 'href="https://example.com"' in out
    assert "href=\"file:" not in out
    assert "javascript:" not in out.replace("<a", "") or "href=\"javascript:" not in out


def test_html_injection_escaped():
    out = md_to_html('<script>alert("x")</script> **粗体**')
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<strong>粗体</strong>" in out


def test_horizontal_rule():
    assert "<hr" in md_to_html("上\n\n---\n\n下")


def test_table_rendered():
    """截图里的表格：`|键|值|` + `|---|---|` 原样显示 → 必须渲染成 HTML table。"""
    out = md_to_html("| 键 | 值 |\n|---|---|\n| 主题偏好 | **深色主题**（dark mode） |\n| 偏好 | 深色主题 |")
    assert "<table" in out and "<th" in out and "<tr>" in out
    assert "主题偏好" in out and "深色主题" in out
    assert "**深色主题**" not in out   # 单元格内的行内 markdown 也解析
    assert out.count("<td") == 4       # 2 行 × 2 列


def test_table_with_alignment_and_no_outer_pipes():
    out = md_to_html("键 | 值\n:--- | ---:\nA | B")
    assert "<table" in out and "A" in out and "B" in out


# Qt 集成测试放在 test_desktop.py（共用 module-scope QApplication fixture）：
# 独立创建 QApplication 会与后续 worker 测试的资源清理竞态，导致全量崩溃。
