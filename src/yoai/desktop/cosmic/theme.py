"""宇宙星球系主题 · 对齐 AMBRACE 服务器控制台 d2.css 原值。

硬约束（原文）：零圆角 / 无阴影 / 无渐变(装饰性) / 装饰性强调色每页≤6处 / 星空只进墨纸档。

双主题：
- light 纸墨：#f4f0e6 底 / #1b1815 墨
- dark  墨纸：#131110 底 / #e9e1d4 墨
强调色：砖红 #8c3f2b、朱红 #d8452a、绿 #4f6b4a、琥珀 #a8642c。
环图六档：同一支砖红谱由深到浅 + 一档灰（--ring1..6）。

字体角色：界面雅黑 / 标题宋体 / 数字 Georgia / 代码 Consolas。
字号阶梯：cap10.5 note11.5 body12.5 lead13 h3=15 h2=16 h1=19 code22 num26 date40。
缓动：cubic-bezier(.2,.7,.3,1)。

生命周期色标（星球光晕）：active 朱红发光 / probation 琥珀微光 /
candidate 灰暗 / retired 深赭熄灭。
"""

from __future__ import annotations

from dataclasses import dataclass

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_PAPER = THEME_LIGHT   # 兼容旧名
THEME_DEEP = THEME_DARK     # 兼容旧名


@dataclass(frozen=True)
class Palette:
    name: str
    paper: str          # 页底
    paper2: str         # 次底（卡片/侧栏）
    ink: str            # 主文字
    dim: str            # 次文字
    weak: str           # 弱文字
    brick: str          # 砖红（强调）
    vermilion: str      # 朱红
    ok: str
    warn: str
    rule: str           # 描边
    ring: tuple[str, ...]
    star: str
    meteor_head: str
    meteor_tail: str

    @classmethod
    def light(cls) -> Palette:
        return cls(
            name=THEME_LIGHT,
            paper="#f4f0e6", paper2="#efe9db",
            ink="#1b1815", dim="#6f665a", weak="#756a5c",
            brick="#8c3f2b", vermilion="#d8452a",
            ok="#4f6b4a", warn="#a8642c", rule="#d8cfbd",
            ring=("#8c3f2b", "#a8563c", "#c1714f", "#d69b76", "#e3bb9c", "#c3bdb1"),
            star="#c2871d",          # 纸色档星点=金（落叶感）
            meteor_head="#c2871d", meteor_tail="#e3ae3c",
        )

    @classmethod
    def dark(cls) -> Palette:
        return cls(
            name=THEME_DARK,
            paper="#131110", paper2="#1a1714",
            ink="#e9e1d4", dim="#a99d8d", weak="#8d8172",
            brick="#c9785f", vermilion="#f0552f",
            ok="#8dbf95", warn="#d3924f", rule="#302b24",
            ring=("#c9785f", "#d98f6d", "#e5a882", "#eec39f", "#f4d8bd", "#4f463d"),
            star="#e9e1d4",
            meteor_head="#fff6e0", meteor_tail="#ffbe96",
        )

    # 兼容旧调用名（main_window / galaxy 里用到）
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

    @classmethod
    def deep(cls) -> Palette:
        return cls.dark()

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
        return "#6f4a0f"

    def lifecycle_color(self, lifecycle: str) -> str:
        return {
            "active": self.vermilion,     # 朱红发光
            "probation": self.warn,       # 琥珀微光
            "candidate": self.weak,       # 灰暗
            "retired": "#6f4a0f",         # 深赭熄灭
        }.get(lifecycle, self.weak)


def qss(p: Palette) -> str:
    """严格按 d2.css 硬约束：零圆角、无阴影、1px 实线、纯色面。

    装饰性强调色（砖红）只用在 ≤6 处：选中标签下划线、主按钮、输入聚焦描边、
    YoAi 名字、悬停态、列表选中文字。其余一律墨色 / 描边色。
    字体角色：界面雅黑 / 标题宋体 / 数字 Georgia。
    """
    song = '"SimSun", "Songti SC", "STSong", serif'
    return f"""
    QMainWindow, QWidget#cosmicRoot {{ background: {p.paper}; color: {p.ink}; }}
    QWidget {{ background: transparent; color: {p.ink}; }}

    /* 标题栏 */
    QLabel#appTitle {{ font-family: {song}; font-size: 19pt; color: {p.ink}; }}
    QLabel#appSub {{ color: {p.weak}; font-size: 10pt; padding-bottom: 3px; }}
    QFrame#rule {{ background: {p.rule}; border: none; }}

    /* 标签页 */
    QTabWidget::pane {{ border: none; background: transparent; }}
    QTabBar::tab {{
        background: transparent; color: {p.dim};
        border: 0; border-bottom: 1px solid {p.rule};
        padding: 8px 18px; margin-right: 0; font-size: 10.5pt;
    }}
    QTabBar::tab:hover {{ color: {p.ink}; }}
    QTabBar::tab:selected {{ color: {p.ink}; border-bottom: 2px solid {p.brick}; }}

    QLabel {{ color: {p.ink}; }}
    QLabel#fieldLabel {{ color: {p.dim}; }}

    /* 对话区与输入区 */
    QFrame#chatFrame {{ background: {p.paper}; border: 1px solid {p.rule}; }}
    QTextBrowser#chatView {{ background: {p.paper}; border: none; font-size: 10.5pt; }}
    QPlainTextEdit#composer {{
        background: {p.paper2}; color: {p.ink};
        border: 1px solid {p.rule}; border-radius: 0; padding: 8px 10px; font-size: 10.5pt;
    }}
    QPlainTextEdit#composer:focus {{ border: 1px solid {p.brick}; }}

    QLineEdit, QPlainTextEdit, QListWidget {{
        background: {p.paper2}; color: {p.ink};
        border: 1px solid {p.rule}; border-radius: 0; padding: 6px;
    }}
    QLineEdit:focus {{ border: 1px solid {p.ink}; }}

    /* 侧栏卡片 */
    QFrame#card {{ background: {p.paper2}; border: 1px solid {p.rule}; }}
    QFrame#card QListWidget {{ background: transparent; border: none; padding: 0; }}
    QLabel#sectionTitle {{ font-family: {song}; font-size: 12pt; color: {p.ink}; }}
    QLabel#countBadge {{
        font-family: Georgia, serif; font-size: 10pt; color: {p.dim};
        border: 1px solid {p.rule}; padding: 0 7px;
    }}
    QLabel#hint {{ color: {p.weak}; font-size: 9.5pt; padding: 4px 0; }}
    QListWidget::item {{ padding: 5px 2px; border-bottom: 1px solid {p.rule}; }}
    QListWidget::item:hover {{ background: {p.paper}; }}
    QListWidget::item:selected {{ background: transparent; color: {p.brick}; }}

    /* 按钮：默认描边 / ghost 无框 / primary 实底砖红 */
    QPushButton {{
        background: transparent; color: {p.ink};
        border: 1px solid {p.rule}; border-radius: 0; padding: 6px 14px;
    }}
    QPushButton:hover {{ color: {p.brick}; border-color: {p.brick}; }}
    QPushButton:disabled {{ color: {p.weak}; border-color: {p.rule}; }}
    QPushButton#ghost {{ border: 1px solid transparent; color: {p.dim}; padding: 5px 10px; }}
    QPushButton#ghost:hover {{ color: {p.ink}; border-color: {p.rule}; }}
    QPushButton#primary {{
        background: {p.brick}; color: {p.paper}; border: 1px solid {p.brick};
        padding: 0 22px; font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {p.ink}; border-color: {p.ink}; color: {p.paper}; }}
    QPushButton#primary:disabled {{ background: {p.paper2}; color: {p.weak}; border-color: {p.rule}; }}

    QComboBox {{
        background: {p.paper2}; color: {p.ink};
        border: 1px solid {p.rule}; border-radius: 0; padding: 4px 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.paper2}; color: {p.ink}; border: 1px solid {p.rule};
        selection-background-color: {p.paper}; selection-color: {p.ink};
    }}
    QSplitter::handle {{ background: transparent; }}
    QToolTip {{ background: {p.paper2}; color: {p.ink}; border: 1px solid {p.rule}; padding: 4px 6px; }}
    QStatusBar {{ color: {p.weak}; background: transparent; }}
    /* 原生滚条藏掉（参考 ::-webkit-scrollbar width:0）——由星球滚条接管 */
    QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; width: 0; height: 0; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: transparent; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    """
