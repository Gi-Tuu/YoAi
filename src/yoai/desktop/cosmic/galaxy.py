"""进化档案星系图 — 把进化树画成星球系（UI-0 档案树视图）。

映射（对齐 AMBRACE 宇宙星球系 + 进化设计）：
- 根节点 = 恒星（居中、最大、带星环、发光）
- 子专家节点 = 行星，按血统深度分布在同心轨道上
- 轨道 = 血统关系；同一父节点的兄弟均匀分布在一段弧上
- 光晕色标 = 生命周期：active 朱红发光 / probation 琥珀微光 / candidate 灰暗 / retired 深赭熄灭
- 点击星球 → 详情卡（名称/版本/父节点/生命周期/能力标签/修改差异/证据/路由理由）
- 背景 = StarfieldWidget 星空；左下角 = 只露一弧的暗星球（设置入口，呼应参考）

纯 Qt Widgets 自绘 + PlanetWidget，零第三方依赖。
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSplitter, QSizePolicy, QVBoxLayout, QWidget,
)

from yoai.desktop.cosmic.planet import PlanetWidget, draw_planet
from yoai.desktop.cosmic.starfield import StarfieldWidget
from yoai.desktop.cosmic.theme import Palette, THEME_PAPER
from yoai.evolution import EvolutionArchive, ExpertNode


class _PlanetField(QWidget):
    """绘制轨道 + 承载星球部件的画布。"""

    def __init__(self, palette: Palette, on_select) -> None:
        super().__init__()
        self.palette = palette
        self.on_select = on_select
        self.planets: list[PlanetWidget] = []
        self.orbits: list[int] = []      # 每个星球所在轨道层级（0=恒星）
        self._selected: PlanetWidget | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def planet_clicked(self, planet: PlanetWidget) -> None:
        for p in self.planets:
            p.set_selected(p is planet)
        self._selected = planet
        self.on_select(planet)

    def layout_nodes(self, archive: EvolutionArchive) -> None:
        """按血统深度把节点摆到同心轨道上。"""
        for p in self.planets:
            p.setParent(None)
            p.deleteLater()
        self.planets, self.orbits = [], []
        root = archive.root
        if root is None:
            return

        # 按深度分组
        by_depth: dict[int, list[ExpertNode]] = {}
        for node in archive.list_nodes():
            depth = self._depth(archive, node)
            by_depth.setdefault(depth, []).append(node)

        # 必须基于真实控件尺寸，否则星球会被摆到可见区外
        w, h = self.width(), self.height()
        if w < 40 or h < 40:
            return  # 布局尚未稳定，等 resizeEvent 再摆
        cx, cy = w * 0.5, h * 0.5
        max_depth = max(by_depth) if by_depth else 0
        base = min(w, h) * 0.10
        gap = min(w, h) * 0.30 / max(1, max_depth)

        for depth, nodes in sorted(by_depth.items()):
            radius_px = base + gap * depth
            count = len(nodes)
            for i, node in enumerate(nodes):
                if depth == 0:
                    px, py = cx, cy
                    size = 34
                    ring = True
                else:
                    angle = -math.pi / 2 + (2 * math.pi * i / max(1, count))
                    # 兄弟节点错开，避免与父节点轨道重叠
                    px = cx + radius_px * math.cos(angle)
                    py = cy + radius_px * math.sin(angle) * 0.78
                    size = max(12, 22 - depth * 2)
                    ring = False
                planet = PlanetWidget(
                    self.palette, lifecycle=node.lifecycle,
                    name=node.name, radius=size, ring=ring,
                )
                planet.setParent(self)   # 必须挂到画布上，否则不显示
                planet.node_id = node.id  # type: ignore[attr-defined]
                planet.move(int(px - planet.width() / 2), int(py - planet.height() / 2))
                planet.show()
                self.planets.append(planet)
                self.orbits.append(depth)
        self._selected = None
        self.update()

    @staticmethod
    def _depth(archive: EvolutionArchive, node: ExpertNode) -> int:
        d, cur, seen = 0, node, set()
        while cur.parent_id and cur.id not in seen:
            seen.add(cur.id)
            parent = archive.get(cur.parent_id)
            if parent is None:
                break
            d += 1
            cur = parent
        return d

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w * 0.5, h * 0.5
        # 同心轨道（虚线弧，颜色用主题 accent 的淡色）
        color = QColor(self.palette.accent)
        color.setAlphaF(0.22 if self.palette.name != THEME_PAPER else 0.35)
        pen = QPen(color, 1.0, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        max_depth = max(self.orbits) if self.orbits else 0
        # 与 layout_nodes 保持同一套轨道半径公式
        all_depth = max([d for d in self.orbits] + [max_depth])
        base = min(w, h) * 0.10
        gap = min(w, h) * 0.30 / max(1, all_depth)
        for depth in range(1, max_depth + 1):
            r = base + gap * depth
            p.drawEllipse(QRectF(cx - r, cy - r * 0.78, r * 2, r * 1.56))
        # 恒星中心微光（即使没节点也画一个淡淡的核心）
        if not self.planets:
            draw_planet(p, cx, cy, 24, self.palette.accent, glow=0.3, ring=True,
                        paper=self.palette.name == THEME_PAPER)
        p.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 档案引用由外部设置
        archive = getattr(self, "_archive", None)
        if archive is not None:
            self.layout_nodes(archive)


class GalaxyView(QWidget):
    """星球系标签页：左星图 + 右详情；星空背景贯穿。"""

    def __init__(self, archive: EvolutionArchive, palette: Palette) -> None:
        super().__init__()
        self.archive = archive
        self.palette = palette
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        title = QLabel("进化星球系  ·  恒星=根节点  行星=专家  轨道=血统  光晕=生命周期")
        header.addWidget(title)
        self.theme_btn = QPushButton("☀ 纸色白天" if self.palette.name != THEME_PAPER else "★ 深空宇宙")
        self.theme_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header.addStretch(1)
        header.addWidget(self.theme_btn)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        # 星空画布（背景 + 星球画布叠加）
        stack = QWidget()
        stack.setMinimumSize(360, 420)
        stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        from PySide6.QtWidgets import QGridLayout
        layered = QGridLayout(stack)
        layered.setContentsMargins(0, 0, 0, 0)
        layered.setColumnStretch(0, 1)
        layered.setRowStretch(0, 1)
        self.starfield = StarfieldWidget(self.palette)
        self.field = _PlanetField(self.palette, self._on_planet_selected)
        self.field._archive = self.archive
        # 两层放进同一个网格单元 → 真正叠加：starfield 底层，field 透明覆盖
        layered.addWidget(self.starfield, 0, 0)
        layered.addWidget(self.field, 0, 0)
        # 确保星球层在星空层之上（同 cell 叠加的 Z 序依赖添加顺序，显式提升更稳）
        self.field.raise_()
        splitter.addWidget(stack)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.addWidget(QLabel("节点详情"))
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("点击一颗星球查看专家节点详情…")
        dl.addWidget(self.detail)
        self.legend = QLabel(
            "生命周期：●active 朱红(发光)  ●probation 琥珀(微光)  "
            "●candidate 灰(暗淡)  ●retired 深赭(熄灭)"
        )
        dl.addWidget(self.legend)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter)
        self._splitter = splitter

        self.field.layout_nodes(self.archive)

    def _on_planet_selected(self, planet: PlanetWidget) -> None:
        node = self.archive.get(getattr(planet, "node_id", ""))
        if node is None:
            return
        lines = [
            f"名称：{node.name}",
            f"ID：{node.id}    版本：v{node.version}",
            f"生命周期：{node.lifecycle}",
            f"父节点：{node.parent_id or '（根节点）'}",
            f"能力标签：{', '.join(node.spec.capability_tags) or '（无）'}",
            f"工具白名单：{', '.join(node.spec.tools) or '（无）'}",
            f"策略偏好：{node.spec.strategy_bias or '（默认）'}",
            f"模型档位：{node.spec.model_tier}",
            f"修改差异：{node.diff or '（无）'}",
            f"证据条数：{len(node.evidence)}",
            f"创建时间：{node.created_at}",
        ]
        if node.spec.prompt_suffix:
            lines.append(f"能力提示：{node.spec.prompt_suffix}")
        self.detail.setPlainText("\n".join(lines))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 首次显示时给星图足够宽度（QSplitter 初始按 sizeHint 会挤扁叠加层）
        self._splitter.setSizes([int(self.width() * 0.62), int(self.width() * 0.38)])
        self.field.layout_nodes(self.archive)

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.starfield.set_palette(palette)
        self.field.palette = palette
        for planet in self.field.planets:
            planet.palette = palette
            planet.update()
        self.field.update()

    def refresh(self) -> None:
        """档案变化后重绘星图。"""
        self.field.layout_nodes(self.archive)
