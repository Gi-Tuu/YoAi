"""外部智能体适配器测试：契约、L2 假命令、L1 投递文件、接入 Channel。

全部离线（假命令 / 临时文件），不真实调用外部智能体。
真实调用另见 test_external_real.py（需本机环境）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:\Competition\YAI Agent Core") / "src"))

from yoai.adapters import (  # noqa: E402
    CliAgentAdapter, ExternalPeer, LaunchOnlyAdapter, PeerAdapter,
)
from yoai.chat import Channel, ChatStore, Message  # noqa: E402


def test_base_contract_is_abstract():
    try:
        PeerAdapter("x")  # type: ignore[abstract]
    except TypeError:
        return
    raise AssertionError("PeerAdapter 应不可直接实例化")


def test_cli_adapter_with_python_echo(tmp_path):
    """用系统 python 当假智能体：把消息原样打印出来。"""
    py = sys.executable
    adapter = CliAgentAdapter(
        "EchoAgent",
        [py, "-c", "import sys; print('回显:' + sys.argv[1])", "{message}"],
        timeout_s=10,
    )
    assert adapter.available() is True
    assert adapter.capabilities() == ["chat", "non_interactive", "auto_reply"]
    result = adapter.send("你好外部世界")
    assert result.ok is True
    assert "回显:你好外部世界" in result.text
    assert result.level == "L2"


def test_cli_adapter_disabled_is_unavailable():
    adapter = CliAgentAdapter("off", ["python", "-c", "print(1)", "{message}"], enabled=False)
    assert adapter.available() is False
    r = adapter.send("x")
    assert r.ok is False and "禁用" in r.detail


def test_cli_adapter_timeout(tmp_path):
    py = sys.executable
    adapter = CliAgentAdapter(
        "Slow",
        [py, "-c", "import time; time.sleep(5)", "{message}"],
        timeout_s=1,
    )
    r = adapter.send("x")
    assert r.ok is False and "超时" in r.detail


def test_launch_adapter_writes_drop_file(tmp_path):
    exe = tmp_path / "FakeApp.exe"
    exe.write_text("fake", encoding="utf-8")
    adapter = LaunchOnlyAdapter(
        "FakeIDE", executable=str(exe), drop_dir=tmp_path / "drops", open_app=False,
    )
    assert adapter.available() is True
    r = adapter.send("请把这段发进群里")
    assert r.ok is False and r.level == "L1" and "人工" in r.detail
    drop = Path(r.meta["drop_file"])
    assert drop.exists() and "请把这段发进群里" in drop.read_text(encoding="utf-8")


def test_launch_adapter_nonexistent_exe(tmp_path):
    adapter = LaunchOnlyAdapter("NoApp", executable=str(tmp_path / "nope.exe"))
    assert adapter.available() is False
    assert adapter.send("x").ok is False


def test_external_peer_in_channel_group(tmp_path):
    """外部 peer 接入 Channel，群广播时收到消息并给出（假的）回复。"""
    py = sys.executable
    adapter = CliAgentAdapter(
        "EchoBot",
        [py, "-c", "import sys; print('外部答:' + sys.argv[1])", "{message}"],
        timeout_s=10,
    )
    ch = Channel(ChatStore(tmp_path / "chat.json"))
    ch.register(ExternalPeer("ext1", adapter))
    group = ch.create_group("混合群", ["ext1"])
    produced = asyncio.run(ch.send(Message.create("user", group.id, "外部你好")))
    replies = [m for m in produced if m.kind == "reply"]
    assert len(replies) == 1
    assert "外部答:外部你好" in replies[0].content


def test_l1_peer_returns_manual_relay_not_fake_answer(tmp_path):
    exe = tmp_path / "Idea.exe"
    exe.write_text("fake", encoding="utf-8")
    adapter = LaunchOnlyAdapter("Idea", executable=str(exe), drop_dir=tmp_path / "d", open_app=False)
    peer = ExternalPeer("ext2", adapter)
    reply = asyncio.run(peer.handle(Message.create("user", "ext2", "hi")))
    assert "人工转发" in reply
    assert "外部答" not in reply   # 没伪造自动回答
