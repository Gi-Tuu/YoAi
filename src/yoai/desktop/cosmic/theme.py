"""纸墨工作台主题与 Qt 样式。"""

from __future__ import annotations

from dataclasses import dataclass

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_PAPER = THEME_LIGHT
THEME_DEEP = THEME_DARK


@dataclass(frozen=True)
class Palette:
    name: str
    paper: str
    paper2: str
    nav: str
    ink: str
    dim: str
    weak: str
    brick: str
    vermilion: str
    ok: str
    warn: str
    rule: str
    accent_soft: str
    on_accent: str
    ring: tuple[str, ...]
    star: str
    meteor_head: str
    meteor_tail: str

    @classmethod
    def light(cls) -> Palette:
        return cls(
            name=THEME_LIGHT,
            paper="#F6F5F1",
            paper2="#FFFFFF",
            nav="#EEEFEA",
            ink="#242522",
            dim="#51574F",
            weak="#62685F",
            brick="#B64732",
            vermilion="#C65A3E",
            ok="#3F6B58",
            warn="#9A641C",
            rule="#D9DBD4",
            accent_soft="#F4E7E2",
            on_accent="#FFFFFF",
            ring=("#B64732", "#C4674F", "#D38770", "#DFA58F", "#EBC4B5", "#C9CDC3"),
            star="#B64732",
            meteor_head="#B64732",
            meteor_tail="#D9DBD4",
        )

    @classmethod
    def dark(cls) -> Palette:
        return cls(
            name=THEME_DARK,
            paper="#171918",
            paper2="#202321",
            nav="#1C1F1D",
            ink="#ECEEE8",
            dim="#B4BAB0",
            weak="#9DA599",
            brick="#E08A72",
            vermilion="#F0552F",
            ok="#8FC7A7",
            warn="#D6A45F",
            rule="#343A34",
            accent_soft="#392923",
            on_accent="#171918",
            ring=("#E08A72", "#E49D86", "#E8B09C", "#EDC4B3", "#F2D8CD", "#596158"),
            star="#ECEEE8",
            meteor_head="#FFF6E8",
            meteor_tail="#E08A72",
        )

    @classmethod
    def deep(cls) -> Palette:
        return cls.dark()

    @property
    def bg_outer(self) -> str:
        return self.paper

    @property
    def bg_inner(self) -> str:
        return self.paper2

    @property
    def surface(self) -> str:
        return self.paper2

    @property
    def border(self) -> str:
        return self.rule

    @property
    def text(self) -> str:
        return self.ink

    @property
    def text_dim(self) -> str:
        return self.dim

    @property
    def accent(self) -> str:
        return self.brick

    @property
    def active(self) -> str:
        return self.vermilion

    @property
    def probation(self) -> str:
        return self.warn

    @property
    def candidate(self) -> str:
        return self.weak

    @property
    def retired(self) -> str:
        return "#6F4A0F"

    def lifecycle_color(self, lifecycle: str) -> str:
        return {
            "active": self.vermilion,
            "probation": self.warn,
            "candidate": self.weak,
            "retired": self.retired,
        }.get(lifecycle, self.weak)


def qss(p: Palette) -> str:
    song = '"SimSun", "Songti SC", "STSong", serif'
    ui = '"Microsoft YaHei", "DengXian", "Segoe UI", sans-serif'
    return f"""
    QMainWindow, QWidget#cosmicRoot {{ background: {p.paper}; color: {p.ink}; }}
    QWidget {{ background: transparent; color: {p.ink}; font-family: {ui}; }}
    QMessageBox#toolApproval {{ background-color: {p.paper2}; color: {p.ink}; }}
    QLabel {{ color: {p.ink}; }}
    QFrame#rule {{ background: {p.rule}; border: none; }}

    QFrame#navRail {{ background: {p.nav}; border-right: 1px solid {p.rule}; }}
    QLabel#brandMark {{ font-family: {song}; font-size: 22pt; font-weight: 700; color: {p.ink}; }}
    QLabel#brandSub {{ color: {p.weak}; font-size: 8.5pt; }}
    QPushButton#navButton {{
        background: transparent; color: {p.dim}; border: none;
        border-left: 3px solid transparent; border-radius: 0;
        padding: 12px 14px; min-height: 42px; text-align: left;
        font-size: 11pt; font-weight: 500;
    }}
    QPushButton#navButton:hover {{ background: {p.paper2}; color: {p.ink}; }}
    QPushButton#navButton:checked {{ background: {p.accent_soft}; color: {p.ink}; border-left-color: {p.brick}; }}
    QPushButton#navButton:disabled {{ color: {p.weak}; }}
    QPushButton#themeButton {{
        background: transparent; color: {p.dim}; border: 1px solid {p.rule};
        border-radius: 6px; padding: 7px 10px; min-height: 32px;
    }}
    QPushButton#themeButton:hover {{ background: {p.paper2}; color: {p.ink}; }}

    QFrame#topBar {{ background: {p.paper2}; border-bottom: 1px solid {p.rule}; }}
    QLabel#pageTitle {{ font-size: 15pt; font-weight: 600; color: {p.ink}; }}
    QLabel#fieldLabel {{ color: {p.weak}; font-size: 9.5pt; }}
    QLabel#modelChip {{
        background: {p.nav}; color: {p.dim}; border: 1px solid {p.rule};
        border-radius: 5px; padding: 2px 7px; font-size: 9pt;
    }}
    QLabel#taskState {{ color: {p.weak}; font-size: 9.5pt; padding: 4px 8px; }}
    QLabel#taskState[state="running"] {{ color: {p.brick}; background: {p.accent_soft}; border-radius: 6px; }}
    QLabel#taskState[state="error"] {{ color: {p.vermilion}; background: {p.accent_soft}; border-radius: 6px; }}
    QLabel#taskState[state="done"] {{ color: {p.ok}; }}

    QTabWidget::pane {{ border: none; background: transparent; }}
    QTabBar::tab {{ background: transparent; color: {p.dim}; border: none; padding: 8px 14px; }}

    QFrame#chatSurface {{ background: {p.paper2}; border: 1px solid {p.rule}; border-radius: 10px; }}
    QTextBrowser#chatView {{ background: {p.paper2}; border: none; font-size: 11pt; }}
    QFrame#composerSurface {{ background: {p.paper2}; border: 1px solid {p.rule}; border-radius: 10px; }}
    QPlainTextEdit#composer {{
        background: transparent; color: {p.ink}; border: none;
        padding: 5px 10px; font-size: 11pt;
    }}
    QPushButton#inkSend {{
        background: transparent; border: 1px solid transparent;
        border-radius: 7px; padding: 0; min-height: 0;
    }}
    QPushButton#inkSend:hover {{ background: {p.nav}; }}
    QPushButton#inkSend:pressed {{ background: {p.accent_soft}; }}
    QPushButton#inkSend:focus {{ border-color: {p.brick}; }}
    QPushButton#inkSend:disabled {{ background: transparent; }}

    QFrame#detailPopup {{ background: {p.paper2}; border: 1px solid {p.rule}; }}
    QPushButton#detailTile {{ padding: 0; min-height: 0; font-size: 9pt; }}
    QFrame#inspector {{ background: {p.paper2}; border-left: 1px solid {p.rule}; }}
    QLabel#inspectorTitle {{ font-size: 12pt; font-weight: 600; }}
    QFrame#inspectorSection {{ background: transparent; border: none; }}
    QLabel#sectionTitle {{ font-size: 10.5pt; font-weight: 600; color: {p.ink}; }}
    QLabel#countBadge {{
        font-family: Georgia, serif; font-size: 9.5pt; color: {p.dim};
        background: {p.nav}; border: none; border-radius: 4px; padding: 2px 7px;
    }}
    QLabel#hint {{ color: {p.weak}; font-size: 9pt; padding: 3px 0; }}
    QFrame#memorySummary {{ background: {p.accent_soft}; border: none; border-radius: 8px; }}
    QLabel#memoryValue {{ color: {p.brick}; font-size: 13pt; font-weight: 600; }}
    QLabel#memorySource {{ color: {p.dim}; font-size: 8.5pt; }}
    QLabel#contextLabel {{ color: {p.weak}; font-size: 9pt; font-weight: 600; }}
    QLabel#contextValue {{ color: {p.ink}; font-size: 10.5pt; }}

    QPushButton {{
        background: {p.paper2}; color: {p.ink}; border: 1px solid {p.rule};
        border-radius: 6px; padding: 7px 14px; min-height: 32px; font-size: 10pt;
    }}
    QPushButton:hover {{ background: {p.nav}; border-color: {p.dim}; }}
    QPushButton:pressed {{ background: {p.accent_soft}; }}
    QPushButton:focus {{ border: 2px solid {p.brick}; }}
    QPushButton:disabled {{ background: {p.nav}; color: {p.weak}; border-color: {p.rule}; }}
    QPushButton#ghost {{ background: transparent; color: {p.dim}; border-color: transparent; }}
    QPushButton#ghost:hover {{ background: {p.nav}; color: {p.ink}; border-color: {p.rule}; }}
    QPushButton#primary {{
        background: {p.brick}; color: {p.on_accent}; border: 1px solid {p.brick};
        padding: 0 20px; font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {p.ink}; border-color: {p.ink}; color: {p.paper2}; }}
    QPushButton#primary:disabled {{ background: {p.nav}; color: {p.weak}; border-color: {p.rule}; }}

    QComboBox {{
        background: {p.paper2}; color: {p.ink}; border: 1px solid {p.rule};
        border-radius: 6px; padding: 6px 10px; min-height: 30px;
    }}
    QComboBox:hover {{ border-color: {p.dim}; }}
    QComboBox:focus {{ border: 2px solid {p.brick}; }}
    QComboBox QAbstractItemView {{
        background: {p.paper2}; color: {p.ink}; border: 1px solid {p.rule};
        selection-background-color: {p.accent_soft}; selection-color: {p.ink};
    }}
    QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget {{
        background: {p.paper2}; color: {p.ink}; border: 1px solid {p.rule};
        border-radius: 6px; padding: 7px; selection-background-color: {p.accent_soft};
        selection-color: {p.ink};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus, QListWidget:focus {{ border: 2px solid {p.brick}; }}
    QListWidget::item {{ padding: 7px 4px; border-bottom: 1px solid {p.rule}; }}
    QListWidget::item:hover {{ background: {p.nav}; }}
    QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.ink}; }}

    QFrame#conversationPanel {{ background: {p.nav}; border: 1px solid {p.rule}; border-radius: 8px; }}
    QFrame#threadPanel {{ background: {p.paper2}; border: 1px solid {p.rule}; border-radius: 8px; }}
    QTextBrowser#messageThread {{ background: {p.paper2}; border: none; font-size: 10.5pt; }}
    QLabel#targetLabel {{ font-size: 12pt; font-weight: 600; }}
    QLineEdit#chatInput {{ background: {p.paper2}; border-radius: 6px; padding: 8px 10px; }}

    QLabel#galaxyTitle {{ font-size: 14pt; font-weight: 600; }}
    QLabel#galaxySub {{ color: {p.weak}; font-size: 9pt; }}
    QLabel#galaxyLegend {{ color: {p.weak}; font-size: 8.5pt; }}
    QPlainTextEdit#nodeDetail {{ background: {p.paper2}; border: 1px solid {p.rule}; border-radius: 8px; font-size: 10pt; }}

    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.rule}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.dim}; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.rule}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QStatusBar {{ background: {p.paper2}; color: {p.weak}; border-top: 1px solid {p.rule}; font-size: 8.5pt; }}
    QStatusBar QLabel {{ color: {p.weak}; font-size: 8.5pt; }}
    QToolTip {{ background: {p.paper2}; color: {p.ink}; border: 1px solid {p.rule}; border-radius: 6px; padding: 6px 8px; }}
    QSplitter::handle {{ background: transparent; }}
    """
