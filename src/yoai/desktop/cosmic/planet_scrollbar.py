"""星球滚条 · 对齐参考 d2.css .psb。

- 原生滚条藏掉（theme.qss 已设 width:0）。
- 单条 16px 宽跟随滚动容器：球体（径向渐变 + 高光）+ 三颗卫星
  （psOrbit 3.4/5.1/7.3s，第二颗反向）+ 按滚动速度伸缩的尾迹。
- 可拖动：按住球拖动直接跳转滚动位置。
- 纸色档给球加一圈细描边，免得亮底上糊成一团。
- 无开屏动画（明确决定不做）。

通过 attach(scroll_area) 把滚条绑到一个 QScrollArea/QPlainTextEdit/QListWidget。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from yoai.desktop.cosmic.theme import Palette, THEME_DARK


class PlanetScrollBar(QWidget):
    """悬浮在滚动容器右缘的星球滚条。"""

    def __init__(self, palette: Palette, target: QWidget | None = None) -> None:
        super().__init__()
        self.palette = palette
        self.target = target
        self._ratio = 0.0
        self._dragging = False
        self._speed = 0.0
        self._t = 0.0
        self.setFixedWidth(16)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def attach(self, target: QWidget) -> None:
        self.target = target
        sb = target.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll)
        self._on_scroll()

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.update()

    def _scroll_range(self):
        if self.target is None:
            return None
        sb = self.target.verticalScrollBar()
        if sb.maximum() <= 0:
            return None
        return sb

    def _on_scroll(self) -> None:
        sb = self._scroll_range()
        if sb is None:
            self.hide()
            return
        new_ratio = sb.value() / sb.maximum()
        self._speed = abs(new_ratio - self._ratio) * 20
        self._ratio = new_ratio
        self.show()
        self.update()

    def _tick(self) -> None:
        self._t += 0.05
        self._speed *= 0.88
        if self._speed < 0.01:
            self._speed = 0.0
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._apply_position(event.position().y())
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._apply_position(event.position().y())
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    def _apply_position(self, y: float) -> None:
        sb = self._scroll_range()
        if sb is None:
            return
        track = max(1, self.height() - 12)
        r = max(0.0, min(1.0, (y - 6) / track))
        sb.setValue(int(r * sb.maximum()))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        track = max(1, self.height() - 12)
        cy = 6 + self._ratio * track
        r = 5.5

        # 尾迹（按速度伸缩，亮头在上/下取决于方向）
        tail_len = min(26, self._speed * 90)
        if tail_len > 1:
            grad = QLinearGradient(0, cy - tail_len, 0, cy)
            hc = QColor(self.palette.vermilion)
            hc.setAlphaF(0.8)
            tc = QColor(self.palette.vermilion)
            tc.setAlphaF(0)
            grad.setColorAt(0.0, tc)
            grad.setColorAt(1.0, hc)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRect(QRectF(cx - 1.5, cy - tail_len, 3, tail_len))

        # 球体（径向渐变 + 高光，参考 .psb-core）
        ball = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.35), r * 1.3)
        ball.setColorAt(0.0, QColor("#ffb489"))
        ball.setColorAt(0.55, QColor(self.palette.brick))
        ball.setColorAt(1.0, QColor("#6d2c1c"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ball)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        if self.palette.name != THEME_DARK:
            p.setPen(QColor(self.palette.rule))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 三颗卫星（3.4 / 5.1 / 7.3s，第二颗反向）
        if self._speed < 0.01:
            for i, (period, reverse, alpha) in enumerate(
                ((3.4, False, 0.75), (5.1, True, 0.5), (7.3, False, 0.35))
            ):
                ang = self._t * (2 * math.pi / period) * (-1 if reverse else 1) + i * 2
                sx = cx + math.cos(ang) * 8
                sy = cy + math.sin(ang) * 8
                c = QColor("#ffe0c0")
                c.setAlphaF(alpha)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawEllipse(QRectF(sx - 1.2, sy - 1.2, 2.4, 2.4))
        p.end()
