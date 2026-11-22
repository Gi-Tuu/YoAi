"""星空背景 · 对齐参考 build_starfield.py + d2.css 页眉星空。

关键（参考原文）：
- 亮度不按 x 一刀切（会留竖断层），走横跨 28%~72% 的 smoothstep 缓坡：
  左侧暗区（标题静区），右侧亮星带，中间平滑过渡。
- 亮星层用 screen 混合、透明度 14s 呼吸（.18↔.72），底板本身一动不动。
- 流星亮头在前：渐变 to right（左端最亮），沿旋转后的 -X 飞，opacity 只在前 11% 有。
- 星空只进墨纸档（dark）；纸色档页眉走纯细线，无星空。
- 时钟/标题静区从亮星层挖掉（这里用左 40% 静区近似）。

纯 QPainter + QTimer，无第三方依赖。
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from yoai.desktop.cosmic.theme import Palette, THEME_DARK

RAMP_X0, RAMP_X1 = 0.28, 0.72
DIM = (28, 86)
LIT = (130, 255)


def _smoothstep(x: float) -> float:
    t = (x - RAMP_X0) / (RAMP_X1 - RAMP_X0)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return t * t * (3 - 2 * t)


def _star_brightness(x_frac: float, rng: random.Random) -> int:
    lo, hi = DIM, LIT
    t = _smoothstep(x_frac)
    a = int(lo[0] + (hi[0] - lo[0]) * t)
    b = int(lo[1] + (hi[1] - lo[1]) * t)
    return rng.randint(a, b)


class StarfieldWidget(QWidget):
    """星空背景；子控件叠在上面。纸色档自动退化为纯色底。"""

    def __init__(self, palette: Palette, *, dense_top: bool = True) -> None:
        super().__init__()
        self.palette = palette
        self.dense_top = dense_top
        self._stars: list[tuple[float, float, float, int, bool]] = []
        self._meteors: list[dict[str, float]] = []
        self._t = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self._seed()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._seed()

    def _seed(self) -> None:
        rng = random.Random(20261121)
        w, h = max(self.width(), 1), max(self.height(), 1)
        self._stars = []
        for _ in range(160):
            xf = rng.random()
            yf = rng.random()
            if self.dense_top:
                yf = 1.0 - rng.random() ** 1.6   # 页眉上密下疏
            bright = _star_brightness(xf, rng)
            size = rng.uniform(0.7, 2.0)
            is_bright = bright >= 175            # 亮星进呼吸层
            self._stars.append((xf, yf, size, bright, is_bright))
        self._meteors = []
        for _ in range(2):
            self._meteors.append({
                "x": rng.uniform(0.55, 1.0), "y": rng.uniform(0.05, 0.55),
                "period": rng.uniform(22, 35), "delay": rng.uniform(0, 20),
                "len": rng.uniform(0.12, 0.22),
            })

    def _tick(self) -> None:
        self._t += 0.05
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(self.palette.paper))

        if self.palette.name != THEME_DARK:
            p.end()
            return   # 纸色档无星空

        # 亮星层呼吸透明度（.18 ↔ .72，14s）
        breath = 0.18 + 0.54 * (0.5 + 0.5 * math.sin(self._t * 2 * math.pi / 14))
        star_c = QColor(self.palette.star)

        # 底板星（静止）+ 亮星层（呼吸，screen 效果用加法近似）
        for xf, yf, size, bright, is_bright in self._stars:
            x, y = xf * w, yf * h
            alpha = bright / 255.0 * (0.55 if not is_bright else 0.35)
            if is_bright:
                alpha *= breath * 2.0     # 呼吸层只叠亮星
            c = QColor(star_c)
            c.setAlphaF(min(1.0, alpha))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QRectF(x - size / 2, y - size / 2, size, size))

        # 流星：亮头在前（左端最亮），沿 -X 飞，opacity 只前 11%
        for m in self._meteors:
            phase = ((self._t + m["delay"]) % m["period"]) / m["period"]
            if phase > 0.11:
                continue
            opacity = 0.8 * (1 - phase / 0.11)
            hx = (m["x"] - phase * 3.0) * w
            hy = (m["y"] + phase * 0.55) * h
            length = m["len"] * w
            # 渐变 to right：左端（前进端）亮，右端（尾）暗
            from PySide6.QtGui import QLinearGradient
            grad = QLinearGradient(hx - length, hy, hx, hy)
            head = QColor(self.palette.meteor_head)
            head.setAlphaF(opacity)
            tail = QColor(self.palette.meteor_tail)
            tail.setAlphaF(0)
            grad.setColorAt(0.0, head)
            grad.setColorAt(1.0, tail)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRect(QRectF(hx - length, hy - 0.6, length, 1.2))
        p.end()
