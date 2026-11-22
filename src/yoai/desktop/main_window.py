"""YoAi 桌面主窗口 — 标准 Qt Widgets 应用。

布局：
  顶部标题栏：宋体标题 + 副标题 + 深浅主题切换
  左侧对话区：消息气泡（ChatView）+ 多行输入（Enter 发送，Shift+Enter 换行）
  右侧侧栏：三张卡片——过程/工具链、个人事实、长期目标（带计数与空状态）
  底部状态栏：本地状态与模型提示

事件映射：把 Core 的 21 类事件渲染成人类可读的过程步，不改事件语义。
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from yoai.agent import YoAiAgent
from yoai.desktop.chat_panel import ChatPanel
from yoai.desktop.widgets import ChatView, Composer, SectionCard
from yoai.desktop.worker import AgentWorker

def _cosmic_qss(palette) -> str:
    """从宇宙主题调色板生成 QSS（主题切换时重设）。"""
    from yoai.desktop.cosmic.theme import qss
    return qss(palette)


EVENT_LABELS = {
    "strategy_selected": "路由",
    "plan_created": "规划",
    "tool_call": "调用工具",
    "tool_result": "工具结果",
    "permission_asked": "请求授权",
    "permission_denied": "拒绝",
    "clarify_requested": "澄清",
    "capability_missing": "能力缺口",
    "tool_discovered": "发现工具",
    "context_compacted": "压缩上下文",
    "memories_recalled": "召回记忆",
    "budget_exceeded": "预算超限",
    "error": "错误",
    "done": "完成",
}


class MainWindow(QMainWindow):
    def __init__(
        self, agent: YoAiAgent, title: str = "YoAi", channel=None,
        registry=None, session_manager=None, evidence_store=None,
        evolution_archive=None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.channel = channel
        self.registry = registry or {}
        self.session_manager = session_manager   # 有则启用会话切换
        self.evidence_store = evidence_store     # 有则自动采集执行证据
        self.evolution_archive = evolution_archive
        self._collector = None
        self._current_task = ""
        self.worker: AgentWorker | None = None
        # 宇宙星球系主题（深空默认，可切纸色）
        from yoai.desktop.cosmic.theme import Palette, THEME_DEEP
        self.palette = Palette.deep()
        self.setStyleSheet(_cosmic_qss(self.palette))
        self.setWindowTitle(title)
        self.resize(960, 680)
        # 显式中文字体：offscreen 下字体库为空，真实 Windows 下用系统雅黑/等线。
        font = QFont()
        font.setFamilies(["Microsoft YaHei", "DengXian", "SimHei"])
        font.setPointSize(10)
        self.setFont(font)
        self._build_ui()
        self._refresh_sidebar()
        self.statusBar().showMessage("离线演示模型已就绪 · 试试「记住我偏好深色主题」")

    # --- UI 构建 ---
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("cosmicRoot")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 14, 20, 8)
        outer.setSpacing(12)

        # 顶部标题栏：宋体标题 + 副标题 + 主题切换
        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("YoAi")
        title.setObjectName("appTitle")
        subtitle = QLabel("个人自主智能体 · 记住你，也记住你的目标")
        subtitle.setObjectName("appSub")
        header.addWidget(title)
        header.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addStretch(1)
        self.header_theme_btn = QPushButton(self._theme_btn_text())
        self.header_theme_btn.setObjectName("ghost")
        self.header_theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_theme_btn.clicked.connect(self._toggle_theme)
        header.addWidget(self.header_theme_btn)
        outer.addLayout(header)

        header_rule = QFrame()
        header_rule.setObjectName("rule")
        header_rule.setFixedHeight(1)
        outer.addWidget(header_rule)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(14)
        outer.addWidget(splitter, 1)

        # 左侧：标签页（我的对话 / 通讯 / 星球系）
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        self.tabs = tabs

        # 标签 0：对话区（保留属性名，兼容已有测试）
        chat_tab = QWidget()
        left_layout = QVBoxLayout(chat_tab)
        left_layout.setContentsMargins(0, 12, 0, 0)
        left_layout.setSpacing(10)
        # 会话选择行（有 SessionManager 时显示）：切换会话即切历史，不再每次新建
        if self.session_manager is not None:
            session_row = QHBoxLayout()
            session_row.setSpacing(8)
            session_label = QLabel("会话")
            session_label.setObjectName("fieldLabel")
            session_row.addWidget(session_label)
            self.session_combo = QComboBox()
            self.session_combo.currentIndexChanged.connect(self._on_switch_session)
            session_row.addWidget(self.session_combo, 1)
            self.new_session_btn = QPushButton("＋ 新建")
            self.new_session_btn.setObjectName("ghost")
            self.new_session_btn.clicked.connect(self._on_new_session)
            session_row.addWidget(self.new_session_btn)
            left_layout.addLayout(session_row)

        from yoai.desktop.cosmic.planet_scrollbar import PlanetScrollBar
        chat_frame = QFrame()
        chat_frame.setObjectName("chatFrame")
        chat_row = QHBoxLayout(chat_frame)
        chat_row.setContentsMargins(16, 12, 4, 12)
        chat_row.setSpacing(4)
        self.chat = ChatView(self.palette)
        chat_row.addWidget(self.chat)
        self.planet_scroll = PlanetScrollBar(self.palette)
        self.planet_scroll.attach(self.chat)
        chat_row.addWidget(self.planet_scroll)
        left_layout.addWidget(chat_frame, 1)

        # 输入区：多行输入 + 发送；下方一行快捷键提示
        composer_frame = QFrame()
        composer_frame.setObjectName("composerFrame")
        input_row = QHBoxLayout(composer_frame)
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)
        self.input = Composer("输入任务，Enter 发送，Shift+Enter 换行…")
        self.input.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setMinimumHeight(48)
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        left_layout.addWidget(composer_frame)
        tabs.addTab(chat_tab, "我的对话")

        # 标签 1：通讯（社交式群聊）
        if self.channel is not None:
            self.chat_panel = ChatPanel(self.channel, registry=self.registry)
            tabs.addTab(self.chat_panel, "通讯")
        else:
            self.chat_panel = None

        # 标签 2：进化星球系（有档案时显示）
        if self.evolution_archive is not None:
            from yoai.desktop.cosmic.galaxy import GalaxyView
            self.galaxy = GalaxyView(self.evolution_archive, self.palette)
            self.galaxy.theme_btn.clicked.connect(self._toggle_theme)
            tabs.addTab(self.galaxy, "星球系")
        else:
            self.galaxy = None
        splitter.addWidget(tabs)

        # 右：侧栏三张卡片（工具链 + 事实 + 目标）
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 12, 0, 0)
        right_layout.setSpacing(12)
        self.trace = QListWidget()
        self.trace_card = SectionCard("过程 · 工具链", self.trace, "发送一条任务后，这里会逐步显示路由、工具调用与结果。")
        right_layout.addWidget(self.trace_card, 3)
        self.facts = QListWidget()
        self.facts_card = SectionCard("个人事实", self.facts, "还没有记住任何事实。试试「记住我偏好深色主题」。")
        right_layout.addWidget(self.facts_card, 2)
        self.goals = QListWidget()
        self.goals_card = SectionCard("长期目标", self.goals, "还没有目标。试试「创建一个目标：完成 YoAi 原型」。")
        right_layout.addWidget(self.goals_card, 2)
        # 左下角风格入口：只露一弧的暗星球 + 浮动卫星（参考 .set-orb / .wx-orb）
        from yoai.desktop.cosmic.dark_orb import DarkOrbButton
        self.orbit_btn = DarkOrbButton(self.palette, "进化星球系")
        self.orbit_btn.setObjectName("orbitEntry")
        self.orbit_btn.clicked.connect(self._open_galaxy)
        right_layout.addWidget(self.orbit_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 360])

        self.setStatusBar(QStatusBar())
        if self.session_manager is not None:
            self._refresh_sessions()

    # --- 宇宙主题 ---
    def _theme_btn_text(self) -> str:
        from yoai.desktop.cosmic.theme import THEME_PAPER
        return "★ 切到深色" if self.palette.name == THEME_PAPER else "☀ 切到纸色"

    def _toggle_theme(self) -> None:
        """深浅切换：重设 QSS + 星球系调色板（对齐参考"主题从右上角球向外推开"的入口）。"""
        from yoai.desktop.cosmic.theme import Palette, THEME_PAPER
        self.palette = Palette.light() if self.palette.name != THEME_PAPER else Palette.deep()
        self.setStyleSheet(_cosmic_qss(self.palette))
        if self.galaxy is not None:
            self.galaxy.set_palette(self.palette)
            self.galaxy.theme_btn.setText(
                "★ 深空宇宙" if self.palette.name == THEME_PAPER else "☀ 纸色白天"
            )
        self.orbit_btn.set_palette(self.palette)
        self.chat.set_palette(self.palette)
        self.header_theme_btn.setText(self._theme_btn_text())
        self._refresh_sidebar()
        self._recolor_trace()
        if hasattr(self, "planet_scroll"):
            self.planet_scroll.set_palette(self.palette)
        self.statusBar().showMessage(
            "已切换到纸色白天" if self.palette.name == THEME_PAPER else "已切换到深空宇宙"
        )

    def _open_galaxy(self) -> None:
        if self.galaxy is not None:
            idx = self.tabs.indexOf(self.galaxy)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)

    # --- 会话切换 ---
    def _refresh_sessions(self) -> None:
        """重建会话下拉；无会话时自动建一个默认会话。"""
        sessions = self.session_manager.list_sessions()
        if not sessions:
            self.session_manager.create("新会话")
            sessions = self.session_manager.list_sessions()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        current = self.session_manager.current
        for s in sessions:
            self.session_combo.addItem(f"{s.name}  ({s.id})", s.id)
        if current:
            idx = self.session_combo.findData(current.id)
            if idx >= 0:
                self.session_combo.setCurrentIndex(idx)
        self.session_combo.blockSignals(False)
        self.agent = self.session_manager.current_agent()
        self._load_history()

    def _on_switch_session(self, _idx: int) -> None:
        sid = self.session_combo.currentData()
        if not sid or self.session_manager is None:
            return
        self.session_manager.switch(str(sid))
        self.agent = self.session_manager.current_agent()
        self._load_history()
        self.statusBar().showMessage(f"已切换到会话：{self.session_manager.current.name}")

    def _on_new_session(self) -> None:
        if self.session_manager is None:
            return
        self.session_manager.create("新会话")
        self._refresh_sessions()
        self.statusBar().showMessage("已新建会话")

    def _load_history(self) -> None:
        """切换会话后把持久化历史渲染回对话区。"""
        self.chat.clear()
        if self.session_manager is None:
            return
        try:
            from yai_core.types import ChatMessage
            history = self.agent.core.memory.history()
            for msg in history:
                role = getattr(msg, "role", "")
                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    content = " ".join(
                        str(p.get("text", "")) for p in content if isinstance(p, dict)
                    )
                label = {"user": "我", "assistant": "YoAi"}.get(role, role)
                self.chat.add_message(label, str(content), time="", render=False)
        except Exception:  # noqa: BLE001 - 历史渲染失败不阻断对话
            pass
        self.chat.render_all()

    # --- 交互 ---
    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        if self.worker is not None and self.worker.isRunning():
            self.statusBar().showMessage("上一任务仍在执行，请稍候")
            return
        self.input.clear()
        self._append_chat("我", text)
        self.trace.clear()
        self.trace_card.set_count(0)
        self.send_btn.setEnabled(False)
        self.send_btn.setText("思考中…")

        from yoai.evolution.fingerprint import fingerprint
        fp = fingerprint(text)
        evidence_meta = {
            "session_id": self.session_manager.current.id if self.session_manager and self.session_manager.current else "",
            "task_fingerprint": fp.key,
            "fingerprint_tags": fp.tags,
            "sample_class": "evolution",   # 日常对话=进化样本；验证样本由 BenchmarkLab 单独构造
            "expert_id": None,             # M1 路由接入后填 RouteDecision.selected_id
            "parent_id": None,
            "model_provider": getattr(self.agent, "model", None),
        }
        worker = AgentWorker(
            self.agent, text, self,
            evidence_store=self.evidence_store, evidence_meta=evidence_meta,
        )
        worker.event_received.connect(self._on_event)
        worker.task_done.connect(self._on_done)
        worker.task_error.connect(self._on_error)
        self.worker = worker
        worker.start()

    def _on_event(self, event_type: str, data: dict[str, Any]) -> None:
        label = EVENT_LABELS.get(event_type, event_type)
        if event_type == "strategy_selected":
            self._append_trace(f"{label}: {data.get('strategy', '')}")
        elif event_type in ("tool_call", "tool_result"):
            tool = data.get("tool", "")
            detail = data.get("arguments", data.get("result", ""))
            self._append_trace(
                f"{label}: {tool} {str(detail)[:120]}",
                kind="dim" if event_type == "tool_result" else "",
            )
        elif event_type == "done":
            self._append_trace(f"{label}", kind="ok")
        elif event_type in ("error", "permission_denied", "budget_exceeded"):
            self._append_trace(label, kind="bad")
        else:
            self._append_trace(label)

    def _on_done(self, final_text: str) -> None:
        self._append_chat("YoAi", final_text or "（无最终文本）")
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self._refresh_sidebar()
        if self.session_manager is not None:
            self.session_manager.touch(delta=2)  # 一轮 user + assistant
        if self.galaxy is not None:
            self.galaxy.refresh()  # 证据/候选变化时重绘星图
        self.statusBar().showMessage("任务完成")

    def _on_error(self, message: str) -> None:
        self._append_chat("YoAi", f"出错了：{message}")
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.statusBar().showMessage("任务失败")

    # --- 渲染辅助 ---
    def _append_chat(self, who: str, text: str) -> None:
        self.chat.add_message(who, text)

    _TRACE_ROLE = Qt.ItemDataRole.UserRole + 1

    def _trace_color(self, kind: str) -> str:
        p = self.palette
        return {"ok": p.ok, "bad": p.vermilion, "dim": p.dim}.get(kind, p.ink)

    def _append_trace(self, text: str, kind: str = "") -> None:
        item = QListWidgetItem(f"{self.trace.count() + 1:02d}  {text}")
        item.setData(self._TRACE_ROLE, kind)
        item.setForeground(QColor(self._trace_color(kind)))
        self.trace.addItem(item)
        self.trace.scrollToBottom()
        self.trace_card.set_count(self.trace.count())

    def _recolor_trace(self) -> None:
        for i in range(self.trace.count()):
            item = self.trace.item(i)
            item.setForeground(QColor(self._trace_color(item.data(self._TRACE_ROLE) or "")))

    def _refresh_sidebar(self) -> None:
        self.facts.clear()
        facts = self.agent.context.list_all()
        for key, value in facts.items():
            self.facts.addItem(QListWidgetItem(f"{key}  ·  {value}"))
        self.facts_card.set_count(len(facts))

        status_mark = {"pending": "○", "active": "●", "done": "✓", "cancelled": "×"}
        self.goals.clear()
        goals = self.agent.goals.list_goals()
        for goal in goals:
            mark = status_mark.get(str(goal["status"]), "○")
            item = QListWidgetItem(f"{mark}  {goal['title']}")
            item.setToolTip(f"状态：{goal['status']}\nID：{goal['id']}")
            self.goals.addItem(item)
        self.goals_card.set_count(len(goals))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 约定
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(2000)
        super().closeEvent(event)


def build_app(agent: YoAiAgent | None = None, title: str = "YoAi") -> tuple[QApplication, MainWindow]:
    """构造 QApplication 与主窗口（不进入事件循环，便于测试 offscreen）。"""
    app = QApplication.instance() or QApplication([])
    win = MainWindow(agent or YoAiAgent(), title)
    return app, win
