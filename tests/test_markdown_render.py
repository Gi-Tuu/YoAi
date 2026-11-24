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


# --- Qt 集成：真把消息塞进视图，确认 HTML 生效 ---

def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_chatview_renders_agent_markdown():
    from yoai.desktop.cosmic.theme import Palette
    from yoai.desktop.widgets import ChatView

    app = _qapp()
    view = ChatView(Palette.light())
    view.add_message("YoAi", "**已记住**深色主题")
    html = view.toHtml()
    # QTextBrowser 把 <strong> 规范化成 span style="font-weight:600"，按实际输出断言
    assert "font-weight:600" in html and "已记住" in html
    assert "**已记住**" not in html


def test_chatview_user_message_stays_plain():
    from yoai.desktop.cosmic.theme import Palette
    from yoai.desktop.widgets import ChatView

    app = _qapp()
    view = ChatView(Palette.light())
    view.add_message("我", "**这不是markdown**")
    html = view.toHtml()
    assert "**这不是markdown**" in html   # 用户输入不被渲染


def test_chat_transcript_renders_peer_markdown():
    from yoai.desktop.cosmic.theme import Palette
    from yoai.desktop.widgets import ChatTranscript

    app = _qapp()
    transcript = ChatTranscript(Palette.light())
    transcript.add_message("peer", "## 结论\n\n- 一条")
    html = transcript.toHtml()
    assert "结论" in html and "<li" in html and "一条</li>" in html
