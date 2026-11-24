"""外部智能体接入 UI 测试（offscreen）：注册表清单、L2 假接入、L1 诚实标注。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.adapters import build_registry  # noqa: E402
from yoai.desktop.main_window import MainWindow  # noqa: E402
from yoai.demo_model import DemoModel  # noqa: E402
from yoai.demo_world import build_demo_channel  # noqa: E402
from yoai.agent import YoAiAgent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_registry_has_all_nine_agents(tmp_path, monkeypatch):
    # 注册表结构测试必须环境无关：两个真实网关 adapter 只有在配置齐备时才
    # available（本机靠 Core .env / 系统环境变量，CI 两者皆无）。这里显式
    # 注入最小配置，让清单断言在任何机器上确定性通过。
    env_file = tmp_path / "core.env"
    env_file.write_text(
        "OPENAI_BASE_URL=https://suanli.example/v2\n"
        "OPENAI_API_KEY=test-key\n"
        "LLM_MODEL=test-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("YAI_CORE_ENV", str(env_file))
    monkeypatch.setenv("YOAI_BASE_URL", "https://suanli.example/v2")
    monkeypatch.setenv("YOAI_API_KEY", "test-key")
    monkeypatch.setenv("YOAI_MODEL", "test-model")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://anthropic.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    reg = build_registry(tmp_path / "drops")
    names = set(reg.keys())
    assert {
        "Claude Code", "OpenCode Zen", "Qoder", "Qoder CN", "Trae CN",
        "MiniMax Code CN", "ZCode", "WorkBuddy", "ChatGPT", "deepseek harness",
        "DeepSeek (Anthropic)", "算里 DeepSeek",
    }.issubset(names)
    # 级别标注正确：L2 = 真实网关 + CLI + Zen，其余 L1
    levels = {n: a.level for n, a in reg.items()}
    assert levels["Claude Code"] == "L2" and levels["OpenCode Zen"] == "L2"
    assert levels["DeepSeek (Anthropic)"] == "L2" and levels["算里 DeepSeek"] == "L2"
    assert levels["Qoder"] == "L1" and levels["ChatGPT"] == "L1"


def test_window_shows_external_agents(app, tmp_path):
    agent = YoAiAgent(model=DemoModel(), data_dir=tmp_path / "main")
    ch = build_demo_channel(tmp_path / "chat")
    reg = build_registry(tmp_path / "drops")
    win = MainWindow(agent, channel=ch, registry=reg)
    panel = win.chat_panel
    # 外部智能体清单：12 个（2 真实网关 + Claude + Zen + 8 L1）
    assert panel.external_list.count() >= 10
    texts = [panel.external_list.item(i).text() for i in range(panel.external_list.count())]
    assert any("Claude Code" in t and "L2" in t for t in texts)
    assert any("Qoder" in t and "L1" in t for t in texts)
    win.close()
