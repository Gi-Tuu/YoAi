"""YoAi 演示世界组装：构造 3 个本地智能体 peer 与一个通讯通道。

刻意用不同的名字与身份提示，让群聊里各 peer 的回复可区分。
"""

from __future__ import annotations

from pathlib import Path

from yoai.agent import YoAiAgent
from yoai.chat import AgentPeer, Channel, ChatStore
from yoai.demo_model import DemoModel


def build_demo_channel(data_dir: str | Path) -> Channel:
    data_dir = Path(data_dir)
    channel = Channel(ChatStore(data_dir / "chat.json"))
    peers = [
        ("p1", "小策"),
        ("p2", "小满"),
        ("p3", "老K"),
    ]
    for pid, name in peers:
        agent = YoAiAgent(model=DemoModel(owner=name), data_dir=data_dir / pid)
        channel.register(AgentPeer(pid, name, agent))
    # 预置一个演示群，打开通讯页就能看到；已存在同名群则复用，避免每次启动累积重复群
    existing = next((g for g in channel.groups() if g.name == "YoAi 工作台"), None)
    if existing is None:
        channel.create_group("YoAi 工作台", [pid for pid, _ in peers])
    return channel
