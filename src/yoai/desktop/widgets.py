"""纸墨工作台的对话、导航与检查器组件。"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
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
    return html.escape(str(text)).replace("\n", "<br>")


class OrbitMark(QWidget):
    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette = palette
        self.setFixedSize(44, 44)

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        ring = QRectF(center.x() - 17, center.y() - 8, 34, 16)
        painter.setPen(QPen(QColor(self.palette.brick), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(ring)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.palette.ink))
        painter.drawEllipse(center, 7, 7)
        painter.setBrush(QColor(self.palette.brick))
        painter.drawEllipse(QRectF(center.x() + 12, center.y() - 11, 5, 5))
        painter.end()


class NavRail(QWidget):
    navigation_requested = Signal(str)
    theme_requested = Signal()

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette = palette
        self.setObjectName("navRail")
        self.setFixedWidth(88)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 18, 0, 14)
        layout.setSpacing(6)

        self.mark = OrbitMark(palette)
        layout.addWidget(self.mark, alignment=Qt.AlignmentFlag.AlignHCenter)
        brand = QLabel("YoAi")
        brand.setObjectName("brandMark")
        brand.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(brand)
        brand_sub = QLabel("个人智能体")
        brand_sub.setObjectName("brandSub")
        brand_sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(brand_sub)
        layout.addSpacing(22)

        self.buttons: dict[str, QPushButton] = {}
        for key, label in (("chat", "我的对话"), ("communication", "通讯"), ("galaxy", "星球系")):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=key: self.navigation_requested.emit(value))
            self.buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.theme_button = QPushButton("切换主题")
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self.theme_requested)
        layout.addWidget(self.theme_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.mark.set_palette(palette)
        self.theme_button.setText("深色主题" if palette.name == "light" else "纸色主题")

    def set_active(self, key: str) -> None:
        for name, button in self.buttons.items():
            button.blockSignals(True)
            button.setChecked(name == key)
            button.blockSignals(False)

    def set_available(self, key: str, available: bool) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setVisible(available)


class ChatView(QTextBrowser):
    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.setObjectName("chatView")
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.palette_ = palette
        self._messages: list[_Msg] = []
        self._render()

    def add_message(self, who: str, text: str, *, time: str | None = None, render: bool = True) -> None:
        self._messages.append(_Msg(who, str(text), time or datetime.now().strftime("%H:%M")))
        if render:
            self._render()

    def clear(self) -> None:  # noqa: D401
        self._messages.clear()
        self._render()

    def render_all(self) -> None:
        self._render()

    def set_palette(self, palette: Palette) -> None:
        self.palette_ = palette
        self._render()

    def toPlainText(self) -> str:  # noqa: N802
        return "\n".join(f"[{m.who}] {m.text}\n" for m in self._messages)

    def _render(self) -> None:
        palette = self.palette_
        if not self._messages:
            self.setHtml(self._welcome_html(palette))
            return
        parts = [f'<body style="background:{palette.paper2}; color:{palette.ink};">']
        for message in self._messages:
            if message.who in USER_NAMES:
                parts.append(self._user_html(message, palette))
            else:
                parts.append(self._agent_html(message, palette))
        parts.append("</body>")
        self.setHtml("".join(parts))
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    @staticmethod
    def _meta(name: str, time: str, name_color: str, palette: Palette, align: str) -> str:
        clock = f'&nbsp;&nbsp;<span style="color:{palette.weak}; font-family:Georgia; font-size:8.5pt;">{_esc(time)}</span>' if time else ""
        return (
            f'<p align="{align}" style="margin:0 0 5px 0;">'
            f'<span style="color:{name_color}; font-weight:600;">{_esc(name)}</span>{clock}</p>'
        )

    def _user_html(self, message: _Msg, palette: Palette) -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 18px 0;">'
            '<tr><td width="20%"></td><td>'
            + self._meta(message.who, message.time, palette.dim, palette, "right")
            + f'<table width="100%" cellspacing="0" cellpadding="12" '
            f'style="background:{palette.nav}; border:1px solid {palette.rule};">'
            f'<tr><td style="color:{palette.ink}; line-height:155%;">{_esc(message.text)}</td></tr></table>'
            '</td></tr></table>'
        )

    def _agent_html(self, message: _Msg, palette: Palette) -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 20px 0;">'
            '<tr><td width="4%"></td><td width="84%">'
            + self._meta(message.who, message.time, palette.brick, palette, "left")
            + f'<div style="color:{palette.ink}; line-height:160%;">{_esc(message.text)}</div>'
            '</td><td width="12%"></td></tr></table>'
        )

    @staticmethod
    def _welcome_html(palette: Palette) -> str:
        rows = "".join(
            f'<tr><td width="24" style="color:{palette.brick};">—</td>'
            f'<td style="color:{palette.dim}; padding:5px 0;">{_esc(example)}</td></tr>'
            for example in WELCOME_EXAMPLES
        )
        return (
            f'<body style="background:{palette.paper2}; color:{palette.ink};">'
            '<table width="100%" cellspacing="0" cellpadding="0"><tr><td width="52"></td><td>'
            f'<p style="font-family:SimSun,Songti SC,STSong; font-size:21pt; color:{palette.ink}; margin:0 0 10px 0;">'
            '你好，我是 YoAi</p>'
            f'<p style="color:{palette.weak}; font-size:10.5pt; line-height:150%; margin:0 0 22px 0;">'
            '我会记住你的偏好与长期目标，跨会话保留。你可以从一句话开始。</p>'
            f'<table cellspacing="0" cellpadding="0">{rows}</table>'
            '</td></tr></table></body>'
        )


class ChatTranscript(QTextBrowser):
    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.setObjectName("messageThread")
        self.palette_ = palette
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self._entries: list[tuple[str, str, bool]] = []
        self._notices: list[str] = []

    def set_palette(self, palette: Palette) -> None:
        self.palette_ = palette
        self._render()

    def add_message(self, name: str, content: str, *, own: bool = False) -> None:
        self._entries.append((str(name), str(content), own))
        self._render()

    def appendPlainText(self, text: str) -> None:  # noqa: N802
        self._notices.append(str(text))
        self._render()

    def toPlainText(self) -> str:  # noqa: N802
        lines = [f"[{'user' if own else name}] {content}\n" for name, content, own in self._entries]
        lines.extend(f"{notice}\n" for notice in self._notices)
        return "".join(lines)

    def clear(self) -> None:  # noqa: D401
        self._entries.clear()
        self._notices.clear()
        super().clear()

    def _render(self) -> None:
        palette = self.palette_
        parts = [f'<body style="background:{palette.paper2}; color:{palette.ink};">']
        for name, content, own in self._entries:
            align = "right" if own else "left"
            background = palette.nav if own else palette.paper2
            border = f"border:1px solid {palette.rule};" if own else ""
            parts.append(
                f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 14px 0;">'
                f'<tr><td align="{align}">'
                f'<span style="color:{palette.brick if not own else palette.dim}; font-size:9pt;">[{_esc(name)}]</span>'
                f'<table cellspacing="0" cellpadding="10" width="78%" '
                f'style="background:{background}; {border}">'
                f'<tr><td style="color:{palette.ink}; line-height:150%;">{_esc(content)}</td></tr></table>'
                '</td></tr></table>'
            )
        for notice in self._notices:
            parts.append(f'<div style="color:{palette.weak}; margin:0 0 8px 0;">{_esc(notice)}</div>')
        parts.append("</body>")
        self.setHtml("".join(parts))
        self.moveCursor(QTextCursor.MoveOperation.End)


class Composer(QPlainTextEdit):
    returnPressed = Signal()

    def __init__(self, placeholder: str = "") -> None:
        super().__init__()
        self.setObjectName("composer")
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setMinimumHeight(56)
        self.setMaximumHeight(120)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802
        self.setPlainText(text)


class SectionCard(QFrame):
    def __init__(self, title: str, body: QWidget, empty_hint: str = "") -> None:
        super().__init__()
        self.setObjectName("inspectorSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("sectionTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.count = QLabel("0")
        self.count.setObjectName("countBadge")
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

    def set_count(self, count: int) -> None:
        self.count.setText(str(count))
        empty = count == 0
        self.hint.setVisible(empty and bool(self.hint.text()))
        self.body.setVisible(not empty)


class MemoryWriteSummary(QFrame):
    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette = palette
        self.setObjectName("memorySummary")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(3)
        self.value = QLabel("本轮记忆 +0")
        self.value.setObjectName("memoryValue")
        self.source = QLabel("时间记忆 · 尚无新增")
        self.source.setObjectName("memorySource")
        layout.addWidget(self.value)
        layout.addWidget(self.source)
        self.set_stats({"calls": 0, "events": 0, "model": 0, "fallback": 0, "supplement": 0})

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.set_running(False)

    def set_running(self, running: bool) -> None:
        if running:
            self.value.setText("正在记录本轮记忆…")
            self.value.setStyleSheet(f"color: {self.palette.brick};")
            self.source.setText("任务完成后显示来源与条数")
        else:
            self.value.setStyleSheet("")

    def set_stats(self, stats: dict[str, int]) -> None:
        events = int(stats.get("events", 0) or 0)
        self.value.setText(f"本轮记忆 +{events}" if events else "本轮未写入记忆")
        self.value.setStyleSheet("" if events else f"color: {self.palette.weak};")
        labels = (("model", "模型"), ("fallback", "规则兜底"), ("supplement", "数字补充"))
        sources = [label for key, label in labels if int(stats.get(key, 0) or 0) > 0]
        self.source.setText("时间记忆 · " + ("、".join(sources) if sources else "无新增"))
