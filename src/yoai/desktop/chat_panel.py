"""通讯页：会话列表、消息线程与外部智能体接入。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from yoai.chat import Channel, Message
from yoai.desktop.chat_worker import ChannelWorker
from yoai.desktop.cosmic.theme import Palette
from yoai.desktop.widgets import ChatTranscript


class ChatPanel(QWidget):
    selection_changed = Signal()

    def __init__(self, channel: Channel, registry=None, parent=None, *, palette: Palette | None = None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.registry = registry or {}
        self.palette = palette or Palette.light()
        self.worker: ChannelWorker | None = None
        self._current_target = ""
        self._build_ui()
        self._refresh_conversations()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(10)
        root.addWidget(splitter)

        left = QFrame()
        left.setObjectName("conversationPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(8)

        conversations_title = QLabel("会话")
        conversations_title.setObjectName("contextLabel")
        left_layout.addWidget(conversations_title)
        self.conversations = QListWidget()
        self.conversations.currentItemChanged.connect(self._on_select_conversation)
        left_layout.addWidget(self.conversations, 3)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.new_group_btn = QPushButton("建群")
        self.new_group_btn.clicked.connect(self._on_new_group)
        self.add_member_btn = QPushButton("拉人")
        self.add_member_btn.clicked.connect(self._on_add_member)
        button_row.addWidget(self.new_group_btn)
        button_row.addWidget(self.add_member_btn)
        left_layout.addLayout(button_row)

        external_title = QLabel("外部智能体 · 双击加入当前群")
        external_title.setObjectName("contextLabel")
        left_layout.addWidget(external_title)
        self.external_list = QListWidget()
        self.external_list.itemDoubleClicked.connect(self._on_add_external)
        left_layout.addWidget(self.external_list, 2)
        splitter.addWidget(left)

        right = QFrame()
        right.setObjectName("threadPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 16, 18, 16)
        right_layout.setSpacing(12)
        self.target_label = QLabel("选择一个会话")
        self.target_label.setObjectName("targetLabel")
        right_layout.addWidget(self.target_label)

        self.messages = ChatTranscript(self.palette)
        self.messages.setPlaceholderText("选择会话后开始聊天…")
        right_layout.addWidget(self.messages, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.chat_input = QLineEdit()
        self.chat_input.setObjectName("chatInput")
        self.chat_input.setPlaceholderText("输入消息，回车发送…")
        self.chat_input.returnPressed.connect(self._on_send)
        self.chat_send_btn = QPushButton("发送")
        self.chat_send_btn.setObjectName("primary")
        self.chat_send_btn.setMinimumHeight(38)
        self.chat_send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.chat_input, 1)
        input_row.addWidget(self.chat_send_btn)
        right_layout.addLayout(input_row)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 620])

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.messages.set_palette(palette)

    def _refresh_conversations(self) -> None:
        target = self._current_target
        self.conversations.clear()
        for peer in self.channel.peers.values():
            item = QListWidgetItem(f"●  {peer.name}")
            item.setData(Qt.ItemDataRole.UserRole, peer.id)
            item.setToolTip(f"单聊 · {peer.id}")
            self.conversations.addItem(item)
        for group in self.channel.groups():
            item = QListWidgetItem(f"◉  {group.name} · {len(group.members)} 人")
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            item.setToolTip(f"群会话 · {group.id}")
            self.conversations.addItem(item)
        if target:
            for index in range(self.conversations.count()):
                if self.conversations.item(index).data(Qt.ItemDataRole.UserRole) == target:
                    self.conversations.setCurrentRow(index)
                    break
        self._refresh_external()

    def _refresh_external(self) -> None:
        self.external_list.clear()
        if not self.registry:
            return
        from yoai.adapters import ExternalPeer

        for name, adapter in self.registry.items():
            description = adapter.describe()
            mark = "✓" if description["available"] else "—"
            item = QListWidgetItem(f"{mark}  [{description['level']}] {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(
                f"{name} · {description['level']}\n"
                f"可用：{description['available']}\n"
                + ("L2：可自动回答" if description["level"] == "L2" else "L1：投递文件，需人工转发")
            )
            self.external_list.addItem(item)

    def _on_add_external(self, item: QListWidgetItem) -> None:
        from yoai.adapters import ExternalPeer

        name = str(item.data(Qt.ItemDataRole.UserRole))
        adapter = self.registry.get(name)
        if not adapter:
            return
        peer_id = f"ext-{name}"
        if peer_id not in self.channel.peers:
            self.channel.register(ExternalPeer(peer_id, adapter))
        group = next((group for group in self.channel.groups() if group.id == self._current_target), None)
        if group:
            added = self.channel.add_member(group.id, peer_id)
            self.status_tip = f"{name} 已加入群「{group.name}」" if added else f"{name} 已在群中"
        else:
            self.status_tip = f"{name} 已注册，选择群后可加入"
        self._refresh_conversations()
        self.selection_changed.emit()

    def _on_select_conversation(self, current, _previous) -> None:
        if current is None:
            self._current_target = ""
            self.target_label.setText("选择一个会话")
            self.messages.clear()
            self.selection_changed.emit()
            return
        self._current_target = str(current.data(Qt.ItemDataRole.UserRole))
        group = next((group for group in self.channel.groups() if group.id == self._current_target), None)
        if group is not None:
            label = group.name
        else:
            peer = self.channel.peers.get(self._current_target)
            label = peer.name if peer else self._current_target
        self.target_label.setText(label)
        self.messages.clear()
        for message in self.channel.history(self._current_target):
            self._render_message(message)
        self.selection_changed.emit()

    def _on_new_group(self) -> None:
        name, ok = QInputDialog.getText(self, "建群", "群名称")
        if not ok or not name.strip():
            return
        peer_ids = list(self.channel.peers.keys())
        group = self.channel.create_group(name.strip(), peer_ids)
        self._refresh_conversations()
        self.status_tip = f"已建群：{group.name}（{len(group.members)} 名成员）"
        self.selection_changed.emit()

    def _on_add_member(self) -> None:
        group = next((group for group in self.channel.groups() if group.id == self._current_target), None)
        if not group:
            self.status_tip = "请先选择一个群会话"
            return
        peer_ids = list(self.channel.peers.keys())
        if not peer_ids:
            self.status_tip = "没有可加入的智能体"
            return
        peer_id, ok = QInputDialog.getItem(self, "拉人", "选择智能体", peer_ids, 0, False)
        if ok and peer_id:
            added = self.channel.add_member(group.id, peer_id)
            self.status_tip = "已拉入" if added else "该成员已在群中"
            self._refresh_conversations()
            self.selection_changed.emit()

    def _on_send(self) -> None:
        text = self.chat_input.text().strip()
        if not text or not self._current_target:
            return
        if self.worker is not None and self.worker.isRunning():
            self.status_tip = "上一条消息仍在投递，请稍候"
            return
        self.chat_input.clear()
        message = Message.create("user", self._current_target, text)
        self._render_message(message)
        self.chat_send_btn.setEnabled(False)
        worker = ChannelWorker(self.channel, message, self)
        worker.message_produced.connect(self._on_produced)
        worker.send_done.connect(lambda _: self._send_finished())
        worker.send_error.connect(self._on_send_error)
        self.worker = worker
        worker.start()

    def _on_produced(self, message: Message) -> None:
        if message.sender == "user":
            return
        self._render_message(message)

    def _send_finished(self) -> None:
        self.chat_send_btn.setEnabled(True)

    def _on_send_error(self, error: str) -> None:
        self.messages.appendPlainText(f"[系统] 发送失败：{error}")
        self.chat_send_btn.setEnabled(True)

    def _render_message(self, message: Message) -> None:
        own = message.sender == "user"
        name = "我" if own else message.meta.get("peer_name", message.sender)
        self.messages.add_message(str(name), message.content, own=own)

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(2000)

    def status(self) -> str:
        return getattr(self, "status_tip", "")
