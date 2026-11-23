"""星球部件 — 程序化贴图自转（纹理转而光不转）+ 独立光照层 + 星环前后两截。

对齐参考 d2.css：
- .planet 用 background-position-x 平移贴图做自转；球面光照/明暗界/大气辉光由 CSS 叠加。
- 星环按物理遮挡拆成球后/球前两截（.rb-back / .rb-front），不整圈压在球脸上。
- 生命周期色标：active 朱红发光 / probation 琥珀微光 / candidate 灰暗 / retired 深赭熄灭。
- 无开屏动画（明确决定不做）。

对外仍提供 draw_planet(...) 与 PlanetWidget，galaxy.py / 图标脚本沿用。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from yoai.desktop.cosmic.theme import Palette
from yoai.desktop.cosmic.texture import planet_tile

TILE = 512


def draw_planet(
    p: QPainter,
    cx: float, cy: float, radius: float,
    color: str,
    *,
    ring: bool = False,
    glow: float = 0.5,
    spin: float = 0.0,
    paper: bool = False,
    kind: str | None = None,
) -> None:
    """画一颗程序化贴图自转的星球。

    - 球体：无缝贴图按 spin 平移（纹理转）；
    - 光照层：固定高光 + 明暗截止线（光不转，物理正确）；
    - 大气辉光：外圈径向渐变（glow 控制亮度）；
    - 星环：后半（球下）与前半（球上，只留下半弧）两截。
    """
    c = QColor(color)
    tile = planet_tile(kind or ("sun" if paper else "moon"))

    # --- 大气辉光（圆形，避免被 widget 裁成方块）---
    gr = radius * (1.7 + 0.5 * glow)
    from PySide6.QtGui import QRadialGradient
    halo = QRadialGradient(cx, cy, gr)
    hc = QColor(c)
    hc.setAlphaF(0.22 * glow + 0.04)
    halo.setColorAt(0.0, hc)
    halo.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(halo)
    p.drawEllipse(QRectF(cx - gr, cy - gr, gr * 2, gr * 2))

    # --- 球体裁剪 + 贴图平铺自转 ---
    p.save()
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.addEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    p.setClipPath(path)
    # 贴图铺满球，按 spin 平移；高度铺满，宽度按半径缩放保持纹理比例
    tile_w = radius * 2.6          # 纹理横向压缩到球面
    offset = -(spin * tile_w) % tile_w
    p.drawTiledPixmap(QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                      tile, QPointF(offset, 0))
    # 光照层（固定，不随贴图转）：左上高光 + 右下明暗截止
    shade = QRadialGradient(cx - radius * 0.32, cy - radius * 0.30, radius * 1.25)
    shade.setColorAt(0.0, QColor(255, 255, 255, 120 if paper else 90))
    shade.setColorAt(0.55, QColor(255, 255, 255, 0))
    shade.setColorAt(1.0, QColor(8, 6, 5, 190 if not paper else 70))
    p.setBrush(shade)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    p.restore()

    # --- 星环：后半（在球下）---
    if ring:
        ring_color = QColor("#f0552f" if not paper else "#c2871d")
        ring_color.setAlphaF(0.75)
        pen = QPen(ring_color)
        pen.setWidthF(max(1.0, radius * 0.045))
        p.save()
        p.translate(cx, cy)
        p.rotate(-16)
        rr = QRectF(-radius * 1.55, -radius * 0.42, radius * 3.1, radius * 0.84)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rr, 0, 180 * 16)
        p.restore()

        # 球本身已在上面画好；前半环压在球上，只留下半弧
        p.save()
        p.translate(cx, cy)
        p.rotate(-16)
        p.setPen(pen)
        p.drawArc(rr, 180 * 16, 180 * 16)
        p.restore()
    p.restore()


class PlanetWidget(QWidget):
    """可点击星球；生命周期决定颜色/光晕/自转。"""

    def __init__(
        self,
        palette: Palette,
        *,
        lifecycle: str = "candidate",
        name: str = "",
        radius: int = 22,
        ring: bool = False,
    ) -> None:
        super().__init__()
        self.palette = palette
        self.lifecycle = lifecycle
        self.name = name
        self.radius = radius
        self.ring = ring
        self.selected = False
        self._spin = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFixedSize(radius * 7, radius * 7)   # 容纳光晕，避免被裁成方块
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{name} · {lifecycle}")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)   # 自转持续

    def set_lifecycle(self, lifecycle: str) -> None:
        self.lifecycle = lifecycle
        self.setToolTip(f"{self.name} · {lifecycle}")
        self.update()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def _tick(self) -> None:
        self._spin = (self._spin + 0.004) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        color = self.palette.lifecycle_color(self.lifecycle)
        glow = {
            "active": 1.0, "probation": 0.5,
            "candidate": 0.16, "retired": 0.0,
        }.get(self.lifecycle, 0.16)
        if self.selected:
            glow = min(1.3, glow + 0.4)
        # active 用太阳贴图（暖色发光），其余用月面；纸色档整体偏日
        is_sun = self.palette.name == "light" or self.lifecycle == "active"
        draw_planet(
            p, cx, cy, self.radius, color,
            ring=self.ring, glow=glow, spin=self._spin,
            paper=is_sun, kind="sun" if is_sun else "moon",
        )
        if self.selected:
            p.setPen(QPen(QColor(self.palette.brick), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - self.radius * 1.4, cy - self.radius * 1.4,
                                 self.radius * 2.8, self.radius * 2.8))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        parent = self.parent()
        if parent is not None and hasattr(parent, "planet_clicked"):
            parent.planet_clicked(self)
        super().mousePressEvent(event)
