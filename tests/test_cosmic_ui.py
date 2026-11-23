"""宇宙星球系 UI 测试：主题、星系图、集成 tab、切换。offscreen。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from yoai.desktop.cosmic.theme import Palette, THEME_DEEP, THEME_PAPER, qss  # noqa: E402
from yoai.desktop.cosmic.galaxy import GalaxyView  # noqa: E402
from yoai.desktop.cosmic.planet import PlanetWidget  # noqa: E402
from yoai.desktop.cosmic.starfield import StarfieldWidget  # noqa: E402
from yoai.desktop.main_window import MainWindow  # noqa: E402
from yoai.evolution import EvolutionArchive, ExpertSpec  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _archive(tmp_path):
    ar = EvolutionArchive(tmp_path / "evo.json")
    root = ar.create_root("通用根", ExpertSpec())
    c = ar.create_child(root.id, "写作专家", ExpertSpec(capability_tags=("writing",)))
    ar.transition(c.id, "probation")
    ar.transition(c.id, "active")
    return ar, root, c


# --- 主题 ---
def test_palettes():
    deep, paper = Palette.deep(), Palette.light()
    assert deep.name == THEME_DEEP and paper.name == THEME_PAPER
    assert deep.lifecycle_color("active") == deep.active
    assert deep.lifecycle_color("retired") == deep.retired
    assert "QTabBar" in qss(deep) and "QScrollBar" in qss(paper)


def test_starfield_runs(app, tmp_path):
    w = StarfieldWidget(Palette.deep())
    w.resize(300, 200)
    w.show()
    assert w.isVisible()
    w.set_palette(Palette.light())
    assert w.palette.name == THEME_PAPER
    w.close()


# --- 星系图 ---
def test_galaxy_shows_all_nodes(app, tmp_path):
    ar, root, child = _archive(tmp_path)
    g = GalaxyView(ar, Palette.deep())
    g.resize(900, 600)
    g.show()
    assert len(g.field.planets) == ar.count() == 2
    ids = {getattr(p, "node_id", "") for p in g.field.planets}
    assert root.id in ids and child.id in ids
    g.close()


def test_planet_click_shows_detail(app, tmp_path):
    ar, root, child = _archive(tmp_path)
    g = GalaxyView(ar, Palette.deep())
    g.resize(900, 600)
    g.show()
    target = next(p for p in g.field.planets if getattr(p, "node_id", "") == child.id)
    g.field.planet_clicked(target)
    text = g.detail.toPlainText()
    assert "写作专家" in text and "active" in text and child.id in text
    assert target.selected is True
    g.close()


def test_galaxy_theme_switch(app, tmp_path):
    ar, _, _ = _archive(tmp_path)
    g = GalaxyView(ar, Palette.deep())
    g.resize(900, 600)
    g.show()
    g.set_palette(Palette.light())
    assert g.palette.name == THEME_PAPER
    assert g.starfield.palette.name == THEME_PAPER
    assert all(p.palette.name == THEME_PAPER for p in g.field.planets)
    g.close()


def test_galaxy_refresh(app, tmp_path):
    ar, root, _ = _archive(tmp_path)
    g = GalaxyView(ar, Palette.deep())
    g.resize(900, 600)
    g.show()
    before = len(g.field.planets)
    ar.create_child(root.id, "新专家", ExpertSpec())
    g.refresh()
    assert len(g.field.planets) == before + 1
    g.close()


# --- 主窗口集成 ---
def test_main_window_has_galaxy_tab(app, tmp_path):
    ar, _, _ = _archive(tmp_path)
    from yoai.agent import YoAiAgent
    from yai_core import ScriptedModel, ModelResponse
    agent = YoAiAgent(model=ScriptedModel([ModelResponse(content="hi")]), data_dir=tmp_path)
    win = MainWindow(agent, evolution_archive=ar)
    win.show()
    assert "星球系" in [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert win.galaxy is not None
    win.close()


def test_main_window_theme_toggle(app, tmp_path):
    ar, _, _ = _archive(tmp_path)
    from yoai.agent import YoAiAgent
    from yai_core import ScriptedModel, ModelResponse
    agent = YoAiAgent(model=ScriptedModel([ModelResponse(content="hi")]), data_dir=tmp_path)
    win = MainWindow(agent, evolution_archive=ar)
    win.show()
    assert win.palette.name == THEME_DEEP
    win._toggle_theme()
    assert win.palette.name == THEME_PAPER
    assert win.galaxy.palette.name == THEME_PAPER
    win._toggle_theme()
    assert win.palette.name == THEME_DEEP
    win.close()


def test_orbit_button_opens_galaxy(app, tmp_path):
    ar, _, _ = _archive(tmp_path)
    from yoai.agent import YoAiAgent
    from yai_core import ScriptedModel, ModelResponse
    agent = YoAiAgent(model=ScriptedModel([ModelResponse(content="hi")]), data_dir=tmp_path)
    win = MainWindow(agent, evolution_archive=ar)
    win.show()
    win._open_galaxy()
    assert win.tabs.currentWidget() is win.galaxy
    win.close()


# --- 重做后：纸墨配色 / 程序化贴图 / 滚条 / 暗星球 ---
def test_paper_ink_palette_values():
    from yoai.desktop.cosmic.theme import Palette
    light, dark = Palette.light(), Palette.dark()
    assert light.paper == "#f4f0e6" and light.ink == "#1b1815"
    assert dark.paper == "#131110" and dark.ink == "#e9e1d4"
    assert len(light.ring) == 6 and len(dark.ring) == 6
    assert "border-radius: 0" in qss(light)  # 零圆角硬约束


def test_lifecycle_colors_use_brick_palette():
    from yoai.desktop.cosmic.theme import Palette
    pal = Palette.dark()
    assert pal.lifecycle_color("active") == pal.vermilion
    assert pal.lifecycle_color("probation") == pal.warn
    assert pal.lifecycle_color("retired") == "#6f4a0f"


def test_planet_texture_is_seamless():
    """程序化贴图左右边界一致（无缝平铺自转）。"""
    from yoai.desktop.cosmic.texture import planet_tile
    tile = planet_tile("moon").toImage()
    w, h = tile.width(), tile.height()
    l = tile.pixelColor(0, h // 2)
    r = tile.pixelColor(w - 1, h // 2)
    assert abs(l.red() - r.red()) <= 2
    assert abs(l.green() - r.green()) <= 2
    assert abs(l.blue() - r.blue()) <= 2


def test_planet_scrollbar_attaches(app, tmp_path):
    from PySide6.QtWidgets import QPlainTextEdit
    from yoai.desktop.cosmic.planet_scrollbar import PlanetScrollBar
    from yoai.desktop.cosmic.theme import Palette
    ed = QPlainTextEdit()
    ed.setPlainText("\n".join("行" * 50 for _ in range(80)))
    bar = PlanetScrollBar(Palette.dark())
    bar.attach(ed)
    ed.verticalScrollBar().setValue(50)
    assert 0 < bar._ratio <= 1
    ed.close()


def test_dark_orb_button(app):
    from yoai.desktop.cosmic.dark_orb import DarkOrbButton
    from yoai.desktop.cosmic.theme import Palette
    b = DarkOrbButton(Palette.dark(), "进化星球系")
    b.show()
    assert b.isVisible() and b.label == "进化星球系"
    b.set_palette(Palette.light())
    assert b.palette.name == "light"
    b.close()
