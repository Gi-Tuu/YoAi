"""左下角暗星球入口 · 对齐参考 d2.css .set-orb。

参考原文：直径 200，球心在窗口下方，只露上面一弧横跨侧栏；中间压黑、
轮廓一圈暖光，指上去微微放大。旁边一颗浮动卫星（参考 .wx-orb）。
这里缩小到适合 YoAi 侧栏的尺寸（120px 球，露约 30px 弧），点击打开星球系。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton

from yoai.desktop.cosmic.theme import Palette, THEME_DARK


class DarkOrbButton(QPushButton):
    """只露上弧的暗星球按钮；点击发 clicked。"""

    def __init__(self, palette: Palette, label: str = "进化星球系") -> None:
        super().__init__()
        self.palette = palette
        self.label = label
        self._t = 0.0
        self.setFixedSize(140, 46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(80)

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.update()

    def _tick(self) -> None:
        self._t += 0.08
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # 球心在按钮下方，只露上弧
        r = 70
        cx, cy = w / 2, h - 8 + r - 22
        c = QColor("#1a1714" if self.palette.name == THEME_DARK else "#6f4a0f")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        # 暖光轮廓（仅上弧可见）
        pen = QPen(QColor(self.palette.brick))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        # 浮动卫星（参考 wx-orb）
        sy = 12 + 3 * math.sin(self._t)
        sat = QColor("#f0552f" if self.palette.name == THEME_DARK else "#c2871d")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(sat)
        p.drawEllipse(QRectF(cx - 46, sy, 7, 7))
        # 标签
        p.setPen(QColor(self.palette.dim))
        p.drawText(QRectF(0, h - 18, w, 16), Qt.AlignmentFlag.AlignCenter, self.label)
        p.end()
