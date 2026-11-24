"""纸墨工作台的对话、导航与检查器组件。"""

from __future__ import annotations

import html
import math
import time
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QTextCursor
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
from yoai.desktop.markdown_html import md_to_html

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
    # 执行过程 / thinking：运行时逐条追加、展开显示；DONE 后折叠成摘要行。
    # 每项 (kind, text)：kind ∈ {"think", "step", "result", "bad"}。
    process: list[tuple[str, str]] | None = None
    process_collapsed: bool = False
    started: float = 0.0      # time.monotonic() 起跑时刻，用于摘要"耗时 Xs"
    finished: float = 0.0
    # 流式文本缓冲：round → 累积文本（每轮模型输出逐字追加，DONE 后定稿）
    stream_rounds: dict[int, str] | None = None
    stream_visible: bool = False   # 流式区是否在正文显示（DONE 后隐藏、摘要代替）
    # 思考缓冲：reasoning 增量是逐 token 的碎片（"try" / "," / "I"），
    # 必须累积成一段连续文本再显示，不能每个 token 一行（2026-11-24 截图反馈）。
    think_buffer: str = ""
    # 思考默认折叠：只留「查看思考过程」入口，不打扰正文阅读（2026-11-24 用户拍板）。
    think_collapsed: bool = True


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
        self.anchorClicked.connect(self._on_anchor)
        self._render()

    def _on_anchor(self, url) -> None:
        """过程块 / 思考段的「展开/折叠」锚点（各自独立切换）。"""
        link = url.toString() if hasattr(url, "toString") else str(url)
        kind = "process" if link.startswith("yoai:process:") else (
            "think" if link.startswith("yoai:think:") else None)
        if kind is None:
            return
        try:
            index = int(link.rsplit(":", 1)[-1])
            msg = self._messages[index]
        except (ValueError, IndexError):
            return
        if kind == "process":
            msg.process_collapsed = not msg.process_collapsed
        else:
            msg.think_collapsed = not msg.think_collapsed
        self._render()

    def begin_process(self, who: str = "YoAi", *, render: bool = True) -> int:
        """新开一条带过程块的助手消息（本轮执行起点）。返回消息索引。"""
        idx = len(self._messages)
        self._messages.append(_Msg(who, "", datetime.now().strftime("%H:%M"),
                                   process=[], started=time.monotonic(),
                                   stream_rounds={}, stream_visible=True))
        if render:
            self._render()
        return idx

    def append_stream_text(self, index: int, round_id: int, delta: str,
                           *, render: bool = True) -> None:
        """模型生成期间逐字追加流式文本（每轮独立，UI 实时刷新）。"""
        if not (0 <= index < len(self._messages)):
            return
        msg = self._messages[index]
        if msg.stream_rounds is None:
            msg.stream_rounds = {}
        msg.stream_rounds[round_id] = msg.stream_rounds.get(round_id, "") + str(delta)
        msg.stream_visible = True
        if render:
            self._render()

    def append_thinking(self, index: int, delta: str, *, render: bool = True) -> None:
        """思考增量累积到同一缓冲——reasoning 是逐 token 碎片，不能逐条成行。"""
        if not (0 <= index < len(self._messages)):
            return
        msg = self._messages[index]
        if delta:
            msg.think_buffer += str(delta)
            if render:
                self._render()

    def streamed_text(self, index: int, round_id: int | None = None) -> str:
        """取流式文本（DONE 定稿用；round_id=None 取最后一轮）。"""
        if not (0 <= index < len(self._messages)):
            return ""
        rounds = self._messages[index].stream_rounds or {}
        if round_id is None:
            return rounds[max(rounds)] if rounds else ""
        return rounds.get(round_id, "")

    def add_process_line(self, index: int, text: str, kind: str = "step",
                         *, render: bool = True) -> None:
        """运行时逐条追加工序/thinking 到指定过程块（同步加载）。"""
        if 0 <= index < len(self._messages) and self._messages[index].process is not None:
            self._messages[index].process.append((kind, str(text)))
            if render:
                self._render()

    def collapse_process(self, index: int, *, render: bool = True) -> None:
        """最终结果返回后折叠过程块，只留摘要行（可点击展开回看）。"""
        if 0 <= index < len(self._messages) and self._messages[index].process is not None:
            msg = self._messages[index]
            msg.process_collapsed = True
            msg.stream_visible = False   # 流式区已定稿到正文，避免重复显示
            msg.finished = time.monotonic()
            if render:
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

    def _process_html(self, message: _Msg, palette: Palette, index: int) -> str:
        """过程块：运行时展开逐条显示 thinking/工序；完成后折叠为摘要行。"""
        lines = message.process or []
        kinds = {"step": "步骤", "result": "结果", "bad": "错误"}
        # thinking 是逐 token 碎片，走 think_buffer 合并显示，不计入"记录数"
        steps = sum(1 for kind, _ in lines if kind == "step")
        elapsed = message.finished - message.started if message.finished else 0
        summary = (f"执行过程 · {len(lines)} 条记录"
                   + (f" · {steps} 步" if steps else "")
                   + (" · 含思考" if message.think_buffer.strip() else "")
                   + (f" · 耗时 {elapsed:.1f}s" if elapsed else ""))
        toggle = f"yoai:process:{index}"
        link_style = f"color:{palette.brick}; text-decoration:none; cursor:pointer;"
        if message.process_collapsed:
            return (
                f'<div style="margin:0 0 8px 0; padding:5px 9px; background:{palette.nav}; '
                f'border:1px solid {palette.rule}; font-size:9.5pt;">'
                f'<a href="{toggle}" style="{link_style}">▸ {_esc(summary)}（点击展开）</a></div>'
            )
        rows = []
        for kind, text in lines:
            if kind == "think":
                continue   # thinking 走下方 think_buffer 合并渲染
            color = palette.vermilion if kind == "bad" else (
                palette.dim if kind == "result" else palette.ink)
            label = kinds.get(kind, kind)
            rows.append(
                f'<div style="margin:3px 0; color:{color}; font-size:9.5pt; line-height:150%;">'
                f'<span style="color:{palette.weak};">[{_esc(label)}]</span> '
                f'{md_to_html(text, link_color=palette.brick, inline=True)}</div>'
            )
        # 思考段：默认折叠只留入口，点击才展开（碎片已累积成一段连续文本）
        think_html = ""
        if message.think_buffer.strip():
            think_link = f"yoai:think:{index}"
            if message.think_collapsed:
                think_html = (
                    f'<div style="margin:6px 0; font-size:9.5pt;">'
                    f'<a href="{think_link}" style="{link_style}">'
                    f'▸ 查看思考过程（{len(message.think_buffer)} 字）</a></div>'
                )
            else:
                think_html = (
                    f'<div style="margin:6px 0; color:{palette.dim}; font-size:9.5pt; '
                    f'line-height:170%; background:{palette.paper2}; padding:6px 9px; '
                    f'border-left:2px solid {palette.weak};">'
                    f'<a href="{think_link}" style="{link_style}">▾ 收起思考过程</a>'
                    f'<div style="margin-top:5px;">'
                    f'{md_to_html(message.think_buffer, link_color=palette.brick)}</div></div>'
                )
        toggle_label = "▾ 收起过程"
        # 流式文本区：运行时逐字显示模型输出（中间轮在过程块内，最终轮进正文）
        streams = ""
        if message.stream_visible and message.stream_rounds:
            for round_id in sorted(message.stream_rounds):
                text = message.stream_rounds[round_id]
                if not text:
                    continue
                streams += (
                    f'<div style="margin:6px 0 2px 0; color:{palette.ink}; '
                    f'line-height:165%; border-left:2px solid {palette.brick}; '
                    f'padding-left:8px;">'
                    f'{md_to_html(text, link_color=palette.brick)}</div>'
                )
        return (
            f'<div style="margin:0 0 10px 0; padding:7px 10px; background:{palette.nav}; '
            f'border:1px solid {palette.rule};">'
            f'<a href="{toggle}" style="{link_style}">{toggle_label}</a>'
            + "".join(rows) + think_html + streams + '</div>'
        )

    def _agent_html(self, message: _Msg, palette: Palette) -> str:
        index = next((i for i, m in enumerate(self._messages) if m is message), 0)
        process = (self._process_html(message, palette, index)
                   if message.process is not None else "")
        body = md_to_html(message.text, link_color=palette.brick) if message.text else ""
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 20px 0;">'
            '<tr><td width="4%"></td><td width="84%">'
            + self._meta(message.who, message.time, palette.brick, palette, "left")
            + process
            + f'<div style="color:{palette.ink}; line-height:160%;">' + body + '</div>'
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
            # 对方（模型/peer）返回的是 Markdown → 渲染；自己的输入按纯文本转义显示
            body = _esc(content) if own else md_to_html(content, link_color=palette.brick)
            parts.append(
                f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 14px 0;">'
                f'<tr><td align="{align}">'
                f'<span style="color:{palette.brick if not own else palette.dim}; font-size:9pt;">[{_esc(name)}]</span>'
                f'<table cellspacing="0" cellpadding="10" width="78%" '
                f'style="background:{background}; {border}">'
                f'<tr><td style="color:{palette.ink}; line-height:150%;">{body}</td></tr></table>'
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
        self.setFixedHeight(52)

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


class SendButton(QPushButton):
    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.setObjectName("inkSend")
        self.setFixedSize(36, 36)
        self.set_palette(palette)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self.update)
        self.set_busy(False)

    def set_palette(self, palette: Palette) -> None:
        self._ink = QColor(palette.ink)
        self.update()

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)
        label = "思考中" if busy else "发送"
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.setCursor(Qt.CursorShape.ArrowCursor if busy else Qt.CursorShape.PointingHandCursor)
        if busy:
            self._clock.start()
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._ink)
        if self._timer.isActive():
            self._paint_wet_ink(painter, self._clock.elapsed())
        else:
            side = 15
            height = side * math.sqrt(3) / 2
            painter.drawPolygon(QPolygonF([
                QPointF(-height / 3, -side / 2),
                QPointF(2 * height / 3, 0),
                QPointF(-height / 3, side / 2),
            ]))

    @staticmethod
    def _brush_tip(ms: int) -> tuple[QPointF, float]:
        seconds = ms / 1000
        angle = 4.05 * seconds + 0.18 * math.sin(3.3 * seconds) - math.pi / 2
        radius = 9.2 + 0.65 * math.sin(2 * angle + 0.8 * seconds)
        point = QPointF(radius * math.cos(angle), radius * math.sin(angle))
        pressure = 1.22 + 0.38 * math.sin(angle + 0.7 * seconds) + 0.16 * math.cos(3 * angle)
        return point, pressure

    def _paint_wet_ink(self, painter: QPainter, now: int) -> None:
        # Anchor each ink impression to its birth time. Only its opacity ages.
        lifetime = 1330
        interval = 12
        start = max(0, now - lifetime)
        first = ((start + interval - 1) // interval) * interval
        color = QColor(self._ink)
        for born in range(first, now, interval):
            point, pressure = self._brush_tip(born)
            freshness = 1 - (now - born) / lifetime
            color.setAlphaF(0.48 * freshness ** 1.8)
            painter.setBrush(color)
            painter.drawEllipse(point, pressure, pressure * 0.90)
        tip, pressure = self._brush_tip(now)
        painter.setBrush(self._ink)
        painter.drawEllipse(tip, pressure, pressure * 0.90)


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
