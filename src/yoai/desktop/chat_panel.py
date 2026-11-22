"""通讯面板 — 像社交软件的会话界面。

组成：会话列表（peer 单聊 / 群）、消息区、输入框、建群/拉人按钮。
消息经 ChannelWorker 在后台发送，channel.on_message 回调把每条消息（含各 peer
回复）送回 UI 追加渲染，不阻塞主线程。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from yoai.chat import Channel, Message
from yoai.desktop.chat_worker import ChannelWorker


class ChatPanel(QWidget):
    def __init__(self, channel: Channel, registry=None, parent=None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.registry = registry or {}
        self.worker: ChannelWorker | None = None
        self._current_target = ""   # peer id 或 group id
        self._build_ui()
        self._refresh_conversations()
        # 渲染统一走 ChannelWorker.message_produced（Qt signal，线程安全）。
        # 不使用 channel.on_message 渲染，避免同一条消息被渲染两次。

    # --- UI ---
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # 左：会话列表 + 建群
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("会话"))
        self.conversations = QListWidget()
        self.conversations.currentItemChanged.connect(self._on_select_conversation)
        left_layout.addWidget(self.conversations)
        btn_row = QHBoxLayout()
        self.new_group_btn = QPushButton("建群")
        self.new_group_btn.clicked.connect(self._on_new_group)
        self.add_member_btn = QPushButton("拉人")
        self.add_member_btn.clicked.connect(self._on_add_member)
        btn_row.addWidget(self.new_group_btn)
        btn_row.addWidget(self.add_member_btn)
        left_layout.addLayout(btn_row)
        # 外部智能体清单（L2 真接入 / L1 仅唤起 / L0 未发现）
        left_layout.addWidget(QLabel("外部智能体（点选加入会话）"))
        self.external_list = QListWidget()
        self.external_list.itemDoubleClicked.connect(self._on_add_external)
        left_layout.addWidget(self.external_list)
        splitter.addWidget(left)

        # 右：消息区 + 输入
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.target_label = QLabel("选择一个会话")
        right_layout.addWidget(self.target_label)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setPlaceholderText("选择会话后开始聊天…")
        right_layout.addWidget(self.messages)
        input_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("输入消息，回车发送到当前会话…")
        self.chat_input.returnPressed.connect(self._on_send)
        self.chat_send_btn = QPushButton("发送")
        self.chat_send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.chat_input)
        input_row.addWidget(self.chat_send_btn)
        right_layout.addLayout(input_row)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

    # --- 会话列表 ---
    def _refresh_conversations(self) -> None:
        self.conversations.clear()
        for peer in self.channel.peers.values():
            item = QListWidgetItem(f"● {peer.name}  ({peer.id})")
            item.setData(Qt.UserRole, peer.id)
            self.conversations.addItem(item)
        for group in self.channel.groups():
            item = QListWidgetItem(f"◉ {group.name}  ({len(group.members)}人)")
            item.setData(Qt.UserRole, group.id)
            self.conversations.addItem(item)
        self._refresh_external()

    def _refresh_external(self) -> None:
        self.external_list.clear()
        if not self.registry:
            return
        from yoai.adapters import ExternalPeer

        for name, adapter in self.registry.items():
            d = adapter.describe()
            mark = "✓" if d["available"] else "✗"
            text = f"{mark} [{d['level']}] {name}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, name)
            item.setToolTip(
                f"{name} · {d['level']}\n"
                f"可用：{d['available']}\n"
                + ("L2：可自动回答" if d["level"] == "L2"
                   else "L1：仅唤起应用 + 投递文件，需人工转发")
            )
            self.external_list.addItem(item)

    def _on_add_external(self, item: QListWidgetItem) -> None:
        """双击外部智能体：注册为 ExternalPeer 并加入当前群（若有）。"""
        from yoai.adapters import ExternalPeer

        name = str(item.data(Qt.UserRole))
        adapter = self.registry.get(name)
        if not adapter:
            return
        peer_id = f"ext-{name}"
        if peer_id not in self.channel.peers:
            self.channel.register(ExternalPeer(peer_id, adapter))
        # 加入当前选中的群
        group = next((g for g in self.channel.groups() if g.id == self._current_target), None)
        if group:
            added = self.channel.add_member(group.id, peer_id)
            self.status_tip = f"{name} 已加入群「{group.name}」" if added else "已在群中"
        else:
            self.status_tip = f"{name} 已注册为 peer（选择一个群后拉入）"
        self._refresh_conversations()

    def _on_select_conversation(self, current, _previous) -> None:
        if current is None:
            self._current_target = ""
            self.target_label.setText("选择一个会话")
            return
        self._current_target = str(current.data(Qt.UserRole))
        # 群会话显示群名，peer 会话显示智能体名
        group = next((g for g in self.channel.groups() if g.id == self._current_target), None)
        if group:
            label = group.name
        else:
            peer = self.channel.peers.get(self._current_target)
            label = peer.name if peer else self._current_target
        self.target_label.setText(f"当前会话：{label}")
        self.messages.clear()
        for msg in self.channel.history(self._current_target):
            self._render_message(msg)

    # --- 建群 / 拉人 ---
    def _on_new_group(self) -> None:
        name, ok = QInputDialog.getText(self, "建群", "群名称：")
        if not ok or not name.strip():
            return
        peer_ids = list(self.channel.peers.keys())
        group = self.channel.create_group(name.strip(), peer_ids)
        self._refresh_conversations()
        self.status_tip = f"已建群：{group.name}（{len(group.members)} 名智能体）"

    def _on_add_member(self) -> None:
        group = next((g for g in self.channel.groups() if g.id == self._current_target), None)
        if not group:
            self.status_tip = "请先选择一个群会话"
            return
        peer_ids = list(self.channel.peers.keys())
        if not peer_ids:
            self.status_tip = "没有可加入的智能体"
            return
        peer_id, ok = QInputDialog.getItem(self, "拉人", "选择智能体：", peer_ids, 0, False)
        if ok and peer_id:
            added = self.channel.add_member(group.id, peer_id)
            self.status_tip = "已拉入群" if added else "该智能体已在群中"
            self._refresh_conversations()

    # --- 发送 ---
    def _on_send(self) -> None:
        text = self.chat_input.text().strip()
        if not text or not self._current_target:
            return
        if self.worker is not None and self.worker.isRunning():
            self.status_tip = "上一条消息仍在投递，请稍候"
            return
        self.chat_input.clear()
        msg = Message.create("user", self._current_target, text)
        self._render_message(msg)  # 立即显示自己发的
        self.chat_send_btn.setEnabled(False)
        worker = ChannelWorker(self.channel, msg, self)
        worker.message_produced.connect(self._on_produced)
        worker.send_done.connect(lambda _: self._send_finished())
        worker.send_error.connect(self._on_send_error)
        self.worker = worker
        worker.start()

    def _on_produced(self, message: Message) -> None:
        # on_message 回调也会渲染；这里跳过 user 自己那条（已即时显示），避免重复
        if message.sender == "user":
            return
        self._render_message(message)

    def _send_finished(self) -> None:
        self.chat_send_btn.setEnabled(True)

    def _on_send_error(self, err: str) -> None:
        self.messages.appendPlainText(f"[系统] 发送失败：{err}")
        self.chat_send_btn.setEnabled(True)

    # --- 渲染 ---
    def _message_line(self, message: Message) -> str:
        name = message.meta.get("peer_name", message.sender)
        return f"[{name}] {message.content}"

    def _render_message(self, message: Message) -> None:
        self.messages.appendPlainText(self._message_line(message) + "\n")

    def status(self) -> str:
        return getattr(self, "status_tip", "")
