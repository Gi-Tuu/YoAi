"""主窗口用的界面组件 · 遵守 cosmic/theme.py 的 d2.css 硬约束。

硬约束：零圆角 / 无阴影 / 无装饰性渐变 / 1px 实线 / 装饰性强调色每页 ≤6 处。

- ChatView   ：消息气泡对话区（富文本渲染；toPlainText 仍导出 "[谁] 内容" 纯文本，
               便于复制与测试，兼容旧行为）。
- Composer   ：多行输入框，Enter 发送、Shift+Enter 换行；保留 QLineEdit 风格的
               text()/setText()/returnPressed 接口，旧代码与测试无需改动。
- SectionCard：侧栏卡片（宋体标题 + Georgia 计数 + 空状态提示 + 内容控件）。
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from yoai.desktop.cosmic.theme import Palette

USER_NAMES = {"我", "user"}

WELCOME_EXAMPLES = (
    "记住我偏好深色主题",
    "创建一个目标：完成 YoAi 原型",
    "列出我的目标",
    "列出我记住的事实",
)


@dataclass
class _Msg:
    who: str
    text: str
    time: str


def _esc(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


class ChatView(QTextBrowser):
    """消息气泡对话区。

    视觉：用户消息右对齐、次底色块；YoAi 消息左对齐、左侧 1px 描边条。
    名字与时间放在气泡上方的小字行；时间用 Georgia（字体角色：数字）。
    """

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.setObjectName("chatView")
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.palette_ = palette
        self._messages: list[_Msg] = []
        self._render()

    # --- 公开接口 ---
    def add_message(self, who: str, text: str, *, time: str | None = None, render: bool = True) -> None:
        self._messages.append(_Msg(who, text, time or datetime.now().strftime("%H:%M")))
        if render:
            self._render()

    def clear(self) -> None:  # noqa: D401 - 覆盖 Qt 槽
        self._messages.clear()
        self._render()

    def render_all(self) -> None:
        self._render()

    def set_palette(self, palette: Palette) -> None:
        self.palette_ = palette
        self._render()

    def toPlainText(self) -> str:  # noqa: N802 - Qt 命名
        """纯文本导出：保持旧格式 "[谁] 内容"，复制/测试都可用。"""
        return "\n".join(f"[{m.who}] {m.text}\n" for m in self._messages)

    # --- 渲染 ---
    def _render(self) -> None:
        p = self.palette_
        if not self._messages:
            self.setHtml(self._welcome_html(p))
            return
        parts = [f'<body style="background:{p.paper}; color:{p.ink};">']
        for m in self._messages:
            parts.append(self._user_html(m, p) if m.who in USER_NAMES else self._agent_html(m, p))
        parts.append("</body>")
        self.setHtml("".join(parts))
        self.moveCursor(QTextCursor.MoveOperation.End)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _meta(name: str, time: str, name_color: str, p: Palette, align: str) -> str:
        return (
            f'<p align="{align}" style="margin:0 0 4px 0;">'
            f'<span style="color:{name_color}; font-weight:600;">{_esc(name)}</span>'
            f'&nbsp;&nbsp;<span style="color:{p.weak}; font-family:Georgia; font-size:9pt;">{time}</span>'
            f"</p>"
        )

    def _user_html(self, m: _Msg, p: Palette) -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 16px 0;">'
            '<tr><td width="22%"></td><td>'
            + self._meta(m.who, m.time, p.dim, p, "right")
            + f'<table width="100%" cellspacing="0" cellpadding="10" '
            f'style="background:{p.paper2}; border:1px solid {p.rule};">'
            f'<tr><td style="color:{p.ink}; line-height:150%;">{_esc(m.text)}</td></tr></table>'
            "</td></tr></table>"
        )

    def _agent_html(self, m: _Msg, p: Palette) -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 16px 0;">'
            "<tr><td>"
            + self._meta(m.who, m.time, p.brick, p, "left")
            + '<table cellspacing="0" cellpadding="0" width="100%"><tr>'
            f'<td width="1" style="background:{p.rule};"></td>'
            f'<td style="padding:4px 0 4px 12px; color:{p.ink}; line-height:150%;">{_esc(m.text)}</td>'
            '<td width="18%"></td>'
            "</tr></table>"
            "</td></tr></table>"
        )

    @staticmethod
    def _welcome_html(p: Palette) -> str:
        items = "".join(
            f'<p style="margin:0 0 6px 0; color:{p.dim};">— {_esc(e)}</p>' for e in WELCOME_EXAMPLES
        )
        return (
            f'<body style="background:{p.paper}; color:{p.ink};">'
            '<p style="margin:48px 0 0 0;"></p>'
            f'<p align="center" style="font-family:SimSun,Songti SC,STSong; font-size:19pt; color:{p.ink}; margin:0;">'
            "你好，我是 YoAi</p>"
            f'<p align="center" style="color:{p.weak}; margin:8px 0 24px 0;">'
            "我会记住你的偏好与长期目标，跨会话保留。试试这样说：</p>"
            '<table align="center" cellspacing="0" cellpadding="14" '
            f'style="border:1px solid {p.rule};"><tr><td>{items}</td></tr></table>'
            "</body>"
        )


class Composer(QPlainTextEdit):
    """多行输入框：Enter 发送，Shift+Enter 换行。兼容 QLineEdit 常用接口。"""

    returnPressed = Signal()

    def __init__(self, placeholder: str = "") -> None:
        super().__init__()
        self.setObjectName("composer")
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setMinimumHeight(48)
        self.setMaximumHeight(120)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    # QLineEdit 兼容
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802
        self.setPlainText(text)


class SectionCard(QFrame):
    """侧栏卡片：标题行（宋体标题 + 计数）+ 空状态提示 + 内容控件。"""

    def __init__(self, title: str, body: QWidget, empty_hint: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("sectionTitle")
        self.count = QLabel("0")
        self.count.setObjectName("countBadge")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.count)
        layout.addLayout(head)

        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)

        self.hint = QLabel(empty_hint)
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.body = body
        layout.addWidget(body, 1)
        self.set_count(0)

    def set_count(self, n: int) -> None:
        self.count.setText(str(n))
        empty = n == 0
        self.hint.setVisible(empty and bool(self.hint.text()))
        self.body.setVisible(not empty)
