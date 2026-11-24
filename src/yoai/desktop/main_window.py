"""YoAi 纸墨工作台主窗口。"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from yoai.agent import YoAiAgent
from yoai.desktop.chat_panel import ChatPanel
from yoai.desktop.cosmic.theme import Palette
from yoai.desktop.widgets import ChatView, Composer, MemoryWriteSummary, NavRail, SectionCard, SendButton
from yoai.desktop.worker import AgentWorker


def _cosmic_qss(palette: Palette) -> str:
    from yoai.desktop.cosmic.theme import qss

    return qss(palette)


EVENT_LABELS = {
    "strategy_selected": "路由",
    "plan_created": "制定计划",
    "tool_call": "调用工具",
    "tool_result": "工具完成",
    "permission_asked": "请求授权",
    "permission_denied": "拒绝授权",
    "clarify_requested": "需要澄清",
    "capability_missing": "能力缺口",
    "tool_discovered": "发现工具",
    "context_compacted": "压缩上下文",
    "memories_recalled": "召回记忆",
    "budget_exceeded": "预算超限",
    "error": "出错",
    "done": "完成",
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        agent: YoAiAgent,
        title: str = "YoAi",
        channel=None,
        registry=None,
        session_manager=None,
        evidence_store=None,
        evolution_archive=None,
        approval_channel=None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.channel = channel
        self.registry = registry or {}
        self.session_manager = session_manager
        self.evidence_store = evidence_store
        self.evolution_archive = evolution_archive
        self.approval_channel = approval_channel
        if approval_channel is not None:
            approval_channel.confirm_requested.connect(self._on_approval_requested)
        self.worker: AgentWorker | None = None
        # 本轮是否出现过内核错误事件（error/permission_denied/budget_exceeded）。
        # Core 允许"报错后仍发 done"，若在 done 里无脑标"已完成"会掩盖失败——
        # 用户看到的是"你没提过"而非"查询根本没成功"（2026-11-24 静默失败根因之一）。
        self._task_had_error = False
        self._inspector_auto_hidden = False

        self.palette = Palette.light()
        self.setStyleSheet(_cosmic_qss(self.palette))
        self.setWindowTitle(title)
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)
        font = QFont()
        font.setFamilies(["Microsoft YaHei", "DengXian", "SimHei", "Segoe UI"])
        font.setPointSize(10)
        self.setFont(font)

        self._build_ui()
        self._refresh_sidebar()
        self._refresh_memory_summary()
        self._update_model_chip()
        self._set_task_state("就绪", "done")
        self.statusBar().showMessage("纸墨工作台已就绪")

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("cosmicRoot")
        self.setCentralWidget(central)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.nav = NavRail(self.palette)
        self.nav.navigation_requested.connect(self._show_page)
        self.nav.theme_requested.connect(self._toggle_theme)
        shell.addWidget(self.nav)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        shell.addWidget(content, 1)

        self._build_header(content_layout)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()
        self.tabs.setObjectName("contentStack")

        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        chat_layout.setContentsMargins(20, 18, 20, 16)
        chat_layout.setSpacing(12)

        chat_surface = QFrame()
        chat_surface.setObjectName("chatSurface")
        chat_surface_layout = QVBoxLayout(chat_surface)
        chat_surface_layout.setContentsMargins(0, 0, 0, 0)
        self.chat = ChatView(self.palette)
        chat_surface_layout.addWidget(self.chat)
        chat_layout.addWidget(chat_surface, 1)

        composer_surface = QFrame()
        composer_surface.setObjectName("composerSurface")
        composer_layout = QVBoxLayout(composer_surface)
        composer_layout.setContentsMargins(1, 1, 8, 5)
        composer_layout.setSpacing(0)
        self.input = Composer("输入任务…")
        self.input.returnPressed.connect(self._on_send)
        composer_layout.addWidget(self.input)

        controls = QHBoxLayout()
        controls.setContentsMargins(10, 0, 0, 0)
        self.model_chip = QLabel("模型 · 离线演示")
        self.model_chip.setObjectName("modelChip")
        controls.addWidget(self.model_chip)
        controls.addStretch(1)
        self.send_btn = SendButton(self.palette)
        self.send_btn.clicked.connect(self._on_send)
        controls.addWidget(self.send_btn)
        composer_layout.addLayout(controls)
        chat_layout.addWidget(composer_surface)
        self.tabs.addTab(chat_tab, "我的对话")

        self.chat_panel = ChatPanel(self.channel, registry=self.registry, palette=self.palette) if self.channel is not None else None
        if self.chat_panel is not None:
            self.chat_panel.selection_changed.connect(self._update_communication_inspector)
            self.tabs.addTab(self.chat_panel, "通讯")

        self.galaxy = None
        if self.evolution_archive is not None:
            from yoai.desktop.cosmic.galaxy import GalaxyView

            self.galaxy = GalaxyView(self.evolution_archive, self.palette)
            self.tabs.addTab(self.galaxy, "星球系")

        self.nav.set_available("communication", self.chat_panel is not None)
        self.nav.set_available("galaxy", self.galaxy is not None)

        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(10)
        body.addWidget(self.tabs)
        self.inspector = self._build_inspector()
        body.addWidget(self.inspector)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        body.setSizes([820, 320])
        self.content_splitter = body
        content_layout.addWidget(body, 1)

        self.setStatusBar(QStatusBar())
        self.status_model_label = QLabel("本地状态")
        self.status_model_label.setObjectName("fieldLabel")
        self.statusBar().addPermanentWidget(self.status_model_label)
        if self.session_manager is not None:
            self._refresh_sessions()
        else:
            self.session_combo = None
            self.new_session_btn = None
            self._load_history()

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(0)

    def _build_header(self, content_layout: QVBoxLayout) -> None:
        header = QFrame()
        header.setObjectName("topBar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)

        self.page_title = QLabel("我的对话")
        self.page_title.setObjectName("pageTitle")
        layout.addWidget(self.page_title)

        if self.session_manager is not None:
            self.session_label = QLabel("会话")
            self.session_label.setObjectName("fieldLabel")
            layout.addWidget(self.session_label)
            self.session_combo = QComboBox()
            self.session_combo.setMinimumWidth(190)
            self.session_combo.setMaximumWidth(260)
            self.session_combo.currentIndexChanged.connect(self._on_switch_session)
            layout.addWidget(self.session_combo)
            self.new_session_btn = QPushButton("＋ 新建")
            self.new_session_btn.setObjectName("ghost")
            self.new_session_btn.clicked.connect(self._on_new_session)
            layout.addWidget(self.new_session_btn)

        layout.addStretch(1)
        self.task_state_label = QLabel("就绪")
        self.task_state_label.setObjectName("taskState")
        layout.addWidget(self.task_state_label)
        self.inspector_toggle_btn = QPushButton("检查器")
        self.inspector_toggle_btn.setObjectName("ghost")
        self.inspector_toggle_btn.clicked.connect(lambda: self._set_inspector_visible(True))
        layout.addWidget(self.inspector_toggle_btn)
        content_layout.addWidget(header)

    def _build_inspector(self) -> QWidget:
        inspector = QFrame()
        inspector.setObjectName("inspector")
        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        head = QHBoxLayout()
        self.inspector_title = QLabel("本轮检查器")
        self.inspector_title.setObjectName("inspectorTitle")
        head.addWidget(self.inspector_title)
        head.addStretch(1)
        self.collapse_inspector_btn = QPushButton("收起")
        self.collapse_inspector_btn.setObjectName("ghost")
        self.collapse_inspector_btn.clicked.connect(lambda: self._set_inspector_visible(False))
        head.addWidget(self.collapse_inspector_btn)
        layout.addLayout(head)

        self.inspector_stack = QStackedWidget()
        main_page = QWidget()
        main_layout = QVBoxLayout(main_page)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        self.trace = QListWidget()
        self.trace_card = SectionCard("执行过程", self.trace, "发送任务后，这里会显示可读的执行步骤。")
        main_layout.addWidget(self.trace_card, 3)
        self.facts = QListWidget()
        self.facts_card = SectionCard("个人事实", self.facts, "还没有个人事实。")
        main_layout.addWidget(self.facts_card, 2)
        self.goals = QListWidget()
        self.goals_card = SectionCard("长期目标", self.goals, "还没有长期目标。")
        main_layout.addWidget(self.goals_card, 2)
        self.memory_summary = MemoryWriteSummary(self.palette)
        main_layout.addWidget(self.memory_summary)
        self.inspector_stack.addWidget(main_page)

        communication_page = QWidget()
        communication_layout = QVBoxLayout(communication_page)
        communication_layout.setContentsMargins(0, 0, 0, 0)
        communication_layout.setSpacing(16)
        self.comm_target_value = self._context_value("当前会话", "选择一个会话")
        self.comm_members_value = self._context_value("会话成员", "—")
        self.comm_external_value = self._context_value("外部智能体", "—")
        communication_layout.addWidget(self.comm_target_value[0])
        communication_layout.addWidget(self.comm_members_value[0])
        communication_layout.addWidget(self.comm_external_value[0])
        communication_layout.addStretch(1)
        self.inspector_stack.addWidget(communication_page)
        layout.addWidget(self.inspector_stack, 1)
        return inspector

    @staticmethod
    def _context_value(title: str, value: str) -> tuple[QWidget, QLabel]:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(title)
        label.setObjectName("contextLabel")
        content = QLabel(value)
        content.setObjectName("contextValue")
        content.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(content)
        return widget, content

    def _show_page(self, key: str) -> None:
        if key == "chat":
            self.tabs.setCurrentIndex(0)
        elif key == "communication" and self.chat_panel is not None:
            self.tabs.setCurrentIndex(self.tabs.indexOf(self.chat_panel))
        elif key == "galaxy":
            self._open_galaxy()

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.chat_panel:
            key = "communication"
            title = "通讯"
            self.inspector_title.setText("会话检查器")
            self.inspector_stack.setCurrentIndex(1)
            self._update_communication_inspector()
        elif widget is self.galaxy:
            key = "galaxy"
            title = "星球系"
            self.inspector_title.setText("本轮检查器")
            self.inspector_stack.setCurrentIndex(0)
        else:
            key = "chat"
            title = "我的对话"
            self.inspector_title.setText("本轮检查器")
            self.inspector_stack.setCurrentIndex(0)
        self.nav.set_active(key)
        self.page_title.setText(title)
        if self.session_manager is not None:
            self.session_label.setVisible(key == "chat")
            self.session_combo.setVisible(key == "chat")
            self.new_session_btn.setVisible(key == "chat")
        if self.galaxy is not None:
            self.galaxy.starfield.set_active(widget is self.galaxy)
        if widget is self.galaxy:
            self._set_inspector_visible(False)
        elif self.width() >= 1100 or self.inspector.isVisible():
            self._set_inspector_visible(True)

    def _set_inspector_visible(self, visible: bool) -> None:
        if self.tabs.currentWidget() is self.galaxy:
            visible = False
        self.inspector.setVisible(visible)
        self.inspector_toggle_btn.setVisible(not visible and self.tabs.currentWidget() is not self.galaxy)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not hasattr(self, "inspector"):
            return
        if self.width() < 1100 and self.inspector.isVisible() and self.tabs.currentWidget() is not self.galaxy:
            self._inspector_auto_hidden = True
            self._set_inspector_visible(False)
        elif self.width() >= 1100 and self._inspector_auto_hidden and self.tabs.currentWidget() is not self.galaxy:
            self._inspector_auto_hidden = False
            self._set_inspector_visible(True)

    def _toggle_theme(self) -> None:
        self.palette = Palette.dark() if self.palette.name == "light" else Palette.light()
        self.setStyleSheet(_cosmic_qss(self.palette))
        self.nav.set_palette(self.palette)
        self.chat.set_palette(self.palette)
        self.send_btn.set_palette(self.palette)
        self.memory_summary.set_palette(self.palette)
        if self.chat_panel is not None:
            self.chat_panel.set_palette(self.palette)
        if self.galaxy is not None:
            self.galaxy.set_palette(self.palette)
        self._recolor_trace()
        self._refresh_sidebar()
        self._refresh_memory_summary()
        self.statusBar().showMessage("已切换到深色主题" if self.palette.name == "dark" else "已切换到纸色主题")

    def _open_galaxy(self) -> None:
        if self.galaxy is not None:
            index = self.tabs.indexOf(self.galaxy)
            if index >= 0:
                self.tabs.setCurrentIndex(index)

    def _refresh_sessions(self) -> None:
        sessions = self.session_manager.list_sessions()
        if not sessions:
            self.session_manager.create("新会话")
            sessions = self.session_manager.list_sessions()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        current = self.session_manager.current
        for session in sessions:
            label = session.name
            try:
                created = datetime.fromisoformat(session.created_at.replace("Z", "+00:00"))
                label = f"{label} · {created:%m月%d日 %H:%M}"
            except ValueError:
                pass
            self.session_combo.addItem(label, session.id)
            self.session_combo.setItemData(self.session_combo.count() - 1, f"会话 ID：{session.id}", Qt.ItemDataRole.ToolTipRole)
        if current:
            index = self.session_combo.findData(current.id)
            if index >= 0:
                self.session_combo.setCurrentIndex(index)
        self.session_combo.blockSignals(False)
        self.agent = self.session_manager.current_agent()
        self._load_history()

    def _on_switch_session(self, index: int) -> None:
        session_id = self.session_combo.currentData()
        if not session_id or self.session_manager is None:
            return
        self.session_manager.switch(str(session_id))
        self.agent = self.session_manager.current_agent()
        self._load_history()
        self._refresh_sidebar()
        self._refresh_memory_summary()
        self._update_model_chip()
        self.statusBar().showMessage(f"已切换到会话：{self.session_manager.current.name}")

    def _on_new_session(self) -> None:
        if self.session_manager is None:
            return
        self.session_manager.create("新会话")
        self._refresh_sessions()
        self._refresh_sidebar()
        self._refresh_memory_summary()
        self._update_model_chip()
        self.statusBar().showMessage("已新建会话")

    @staticmethod
    def _clean_final_text(text: str) -> str:
        def replace_tool_output(match: re.Match[str]) -> str:
            inner = re.sub(r"<[^>]+>", "", match.group(1))
            return html.unescape(inner).strip()

        cleaned = re.sub(
            r"<tool_output\b[^>]*>(.*?)</tool_output>",
            replace_tool_output,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def _load_history(self) -> None:
        self.chat.clear()
        if self.session_manager is None:
            return
        try:
            history = self.agent.core.memory.history()
            for message in history:
                role = getattr(message, "role", "")
                if role not in ("user", "assistant"):
                    continue
                content = getattr(message, "content", "")
                if isinstance(content, list):
                    content = " ".join(
                        str(part.get("text", "")) for part in content if isinstance(part, dict)
                    )
                label = {"user": "我", "assistant": "YoAi"}.get(role, role)
                cleaned = self._clean_final_text(str(content)) if role == "assistant" else str(content)
                self.chat.add_message(label, cleaned, time="", render=False)
        except Exception:  # noqa: BLE001
            pass
        self.chat.render_all()

    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        if self.worker is not None and self.worker.isRunning():
            self.statusBar().showMessage("上一任务仍在执行，请稍候")
            return
        self.input.clear()
        self._append_chat("我", text)
        self._task_had_error = False   # 新一轮清零
        self.trace.clear()
        self.trace_card.set_count(0)
        self.send_btn.set_busy(True)
        self.memory_summary.set_running(True)
        self._set_task_state("执行中", "running")
        self.statusBar().showMessage("任务执行中…")

        from yoai.evolution.fingerprint import fingerprint

        task_fingerprint = fingerprint(text)
        evidence_meta = {
            "session_id": self.session_manager.current.id if self.session_manager and self.session_manager.current else "",
            "task_fingerprint": task_fingerprint.key,
            "fingerprint_tags": task_fingerprint.tags,
            "sample_class": "evolution",
            "expert_id": None,
            "parent_id": None,
            "model_provider": getattr(self.agent, "model", None),
        }
        worker = AgentWorker(
            self.agent,
            text,
            self,
            evidence_store=self.evidence_store,
            evidence_meta=evidence_meta,
        )
        worker.event_received.connect(self._on_event)
        worker.task_done.connect(self._on_done)
        worker.task_error.connect(self._on_error)
        self.worker = worker
        worker.start()

    def _on_event(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type in ("tier_changed", "model_message"):
            return
        label = EVENT_LABELS.get(event_type, event_type)
        if event_type == "strategy_selected":
            strategy = data.get("strategy", "")
            self._append_trace(f"{label}：{strategy}")
        elif event_type == "tool_call":
            self._append_trace(f"{label}：{data.get('tool', '')}", detail=str(data.get("arguments", "")))
        elif event_type == "tool_result":
            self._append_trace(f"{label}：{data.get('tool', '')}", kind="dim", detail=str(data.get("result", "")))
        elif event_type == "done":
            self._append_trace(label, kind="ok")
        elif event_type in ("error", "permission_denied", "budget_exceeded"):
            # 静默失败修复：错误不能只躺在 trace 的 tooltip 里——
            # 主对话区必须可见，并标记本轮失败，避免 agent 把失败当"没有记忆"回答。
            self._task_had_error = True
            reason = data.get("error") or data.get("reason") or data.get("message") or str(data)
            self._append_trace(label, kind="bad", detail=str(data))
            self._append_chat("YoAi", f"⚠️ {label}：{reason}")
        else:
            self._append_trace(label)

    def _on_approval_requested(self, tool: str, shown_json: str, loop, future) -> None:
        """主线程弹窗：用户确认/拒绝 Core 的写操作审批请求。"""
        from PySide6.QtWidgets import QMessageBox
        import json as _json
        try:
            shown = _json.loads(shown_json)
            import pprint
            detail = pprint.pformat(shown, width=60, sort_dicts=False)
        except Exception:  # noqa: BLE001
            detail = shown_json
        limit = detail if len(detail) <= 900 else detail[:900] + "\n…（已截断）"
        reason = shown.get("reason", "") if isinstance(shown, dict) else ""
        prompt = shown.get("prompt", "") if isinstance(shown, dict) else ""
        text = f"YoAi 请求执行工具：{tool}\n\n"
        if prompt or reason:
            text += f"理由：{prompt or reason}\n\n"
        text += f"参数/上下文：\n{limit}\n\n确认执行吗？"
        answer = QMessageBox.question(
            self, "工具执行确认", text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,   # 默认拒绝（失败关闭）
        )
        approved = answer == QMessageBox.Yes
        from yoai.desktop.approval import set_future
        loop.call_soon_threadsafe(set_future, future, approved)
        self._append_trace(f"审批：{tool} → {'同意' if approved else '拒绝'}",
                           kind="ok" if approved else "bad")

    def _on_done(self, final_text: str) -> None:
        cleaned = self._clean_final_text(final_text) or "（任务完成，但没有返回最终文本）"
        self._append_chat("YoAi", cleaned)
        self.send_btn.set_busy(False)
        self._refresh_sidebar()
        self._refresh_memory_summary()
        if self.session_manager is not None:
            self.session_manager.touch(delta=2)
        if self.galaxy is not None:
            self.galaxy.refresh()
        if self._task_had_error:
            # Core 可能"报错后仍完成"——此时上方的回答可能基于失败的工具调用，
            # 状态必须标失败，不能让用户误以为查询成功但"库里没有"。
            self._set_task_state("部分失败", "error")
            self.statusBar().showMessage("本轮出现过执行错误，请核对上方回答")
        else:
            self._set_task_state("已完成", "done")
            self.statusBar().showMessage("任务完成")

    def _on_error(self, message: str) -> None:
        self._append_chat("YoAi", f"任务失败：{message}")
        self.send_btn.set_busy(False)
        self.memory_summary.set_running(False)
        self._set_task_state("失败", "error")
        self.statusBar().showMessage("任务失败，可修改输入后重试")

    def _append_chat(self, who: str, text: str) -> None:
        self.chat.add_message(who, text)

    def _set_task_state(self, text: str, state: str) -> None:
        self.task_state_label.setText(text)
        self.task_state_label.setProperty("state", state)
        self.task_state_label.style().unpolish(self.task_state_label)
        self.task_state_label.style().polish(self.task_state_label)

    def _update_model_chip(self) -> None:
        provider = getattr(self.agent, "model", None)
        base = getattr(provider, "base", provider)
        model = ""
        if hasattr(base, "_config"):
            try:
                model = str(base._config()[2])
            except Exception:  # noqa: BLE001
                model = ""
        if not model:
            model = "离线 Demo" if type(base).__name__ == "DemoModel" else getattr(base, "name", type(base).__name__)
        self.model_chip.setText(f"模型 · {model}")
        self.status_model_label.setText(f"{model} · 本地状态已加载")

    def _refresh_memory_summary(self) -> None:
        if hasattr(self.agent, "last_write_stats"):
            self.memory_summary.set_stats(self.agent.last_write_stats())
        else:
            self.memory_summary.set_running(False)

    def _update_communication_inspector(self) -> None:
        panel = self.chat_panel
        if panel is None:
            return
        target = panel._current_target
        if not target:
            self.comm_target_value[1].setText("选择一个会话")
            self.comm_members_value[1].setText("—")
        else:
            group = next((group for group in panel.channel.groups() if group.id == target), None)
            if group is not None:
                self.comm_target_value[1].setText(f"{group.name} · {len(group.members)} 人")
                names = [panel.channel.peers[member].name for member in group.members if member in panel.channel.peers]
                self.comm_members_value[1].setText("、".join(names) or "—")
            else:
                peer = panel.channel.peers.get(target)
                self.comm_target_value[1].setText(peer.name if peer else target)
                self.comm_members_value[1].setText("单聊")
        levels = {"L2": 0, "L1": 0, "L0": 0}
        for adapter in panel.registry.values():
            level = adapter.level
            levels[level] = levels.get(level, 0) + 1
        self.comm_external_value[1].setText(
            f"L2 自动回答 {levels.get('L2', 0)} · L1 人工接力 {levels.get('L1', 0)}"
        )

    _TRACE_ROLE = Qt.ItemDataRole.UserRole + 1

    def _trace_color(self, kind: str) -> str:
        return {"ok": self.palette.ok, "bad": self.palette.vermilion, "dim": self.palette.weak}.get(kind, self.palette.ink)

    def _append_trace(self, text: str, kind: str = "", detail: str = "") -> None:
        item = QListWidgetItem(f"{self.trace.count() + 1:02d}  {text}")
        item.setData(self._TRACE_ROLE, kind)
        if detail:
            item.setToolTip(detail[:1000])
        item.setForeground(QColor(self._trace_color(kind)))
        self.trace.addItem(item)
        self.trace.scrollToBottom()
        self.trace_card.set_count(self.trace.count())

    def _recolor_trace(self) -> None:
        for index in range(self.trace.count()):
            item = self.trace.item(index)
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

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.approval_channel is not None:
            # 所有等待中的审批一律拒绝，避免 worker 卡在 confirm() 不退
            self.approval_channel.shutdown.emit()
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(2000)
        if self.chat_panel is not None:
            self.chat_panel.shutdown()
        if self.galaxy is not None:
            self.galaxy.starfield.set_active(False)
        super().closeEvent(event)


def build_app(agent: YoAiAgent | None = None, title: str = "YoAi") -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication([])
    # 实操工具（文件/联网）：默认开启；设 YOAI_BUILTIN_TOOLS=0 可关闭。
    # 写操作受 workspace/ 白名单 gate 约束，读/联网无需授权。
    import os
    enable_tools = os.environ.get("YOAI_BUILTIN_TOOLS", "1") != "0"
    window = MainWindow(agent or YoAiAgent(builtin_tools=enable_tools), title)
    return app, window
