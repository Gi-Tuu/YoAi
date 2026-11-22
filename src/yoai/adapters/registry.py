"""YoAi 外部智能体注册表 — 本机 9 个智能体的接入清单。

事实来源：docs/AGENT-PROBE.md（实测）。每个条目有明确的 level，
不把 L1/L0 伪装成 L2。用户可在 registry 里启用/禁用、改命令模板。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoai.adapters.base import PeerAdapter
from yoai.adapters.cli_adapter import CliAgentAdapter
from yoai.adapters.launch_adapter import LaunchOnlyAdapter
from yoai.adapters.zen_adapter import ZenAdapter, DEFAULT_AUTH

# 真实模型适配器在 build_registry() 内延迟导入，避免模块加载期的循环导入：
# registry → yoai.models → deepseek_adapter → yoai.adapters.base → adapters/__init__ → registry


# L2 真接入：非交互 CLI（claude 直连 bash 可用，但本会话沙箱拦子进程）
L2_AGENTS: list[dict[str, Any]] = [
    {
        "name": "Claude Code",
        "command": ["claude", "-p", "{message}"],
        "timeout_s": 60.0,
        "enabled": True,
    },
]

# OpenCode Zen：key 有效、69 模型可见；当前额度不足，适配器会如实返回 402/429
ZEN_AGENT = {"name": "OpenCode Zen", "model": "gpt-5.4-nano", "enabled": True}

# L1 仅唤起：Electron/IDE，只有 URL 协议或可执行文件路径，无消息 API
L1_AGENTS: list[dict[str, Any]] = [
    {"name": "Qoder", "url": "qoder://yoai", "exe": r"E:\agent\Qoder\Qoder.exe"},
    {"name": "Qoder CN", "url": "qoder-cn://yoai", "exe": r"E:\agent\Qoder CN\Qoder CN.exe"},
    {"name": "Trae CN", "url": "trae-cn://yoai", "exe": r"E:\agent\Trae CN\Trae CN.exe"},
    {"name": "MiniMax Code CN", "url": "minimax-cn://yoai", "exe": r"E:\agent\MiniMax Code CN\MiniMax Code.exe"},
    {"name": "ZCode", "url": "zcode://yoai", "exe": r"E:\agent\zcode\ZCode.exe"},
    {"name": "WorkBuddy", "url": "workbuddy://yoai", "exe": r"E:\agent\WorkBuddy\WorkBuddy.exe"},
    {"name": "ChatGPT", "url": "", "exe": r"C:\Users\sheng\AppData\Local\Microsoft\WindowsApps\chatgpt-desktop.exe"},
    {"name": "deepseek harness", "url": "", "exe": r"C:\Users\sheng\AppData\Local\Programs\DeepSeek Harness\DeepSeek Harness.exe"},
]


def build_registry(drop_dir: str | Path | None = None) -> dict[str, PeerAdapter]:
    """构造全部适配器。drop_dir 为 L1 投递文件目录。"""
    # 延迟导入真实模型适配器（避免上述循环导入）
    from yoai.models import DeepSeekAnthropicAdapter, SuanliAdapter
    l2_model_adapters = [DeepSeekAnthropicAdapter, SuanliAdapter]

    registry: dict[str, PeerAdapter] = {}

    # 真实模型网关优先（HTTP，不受子进程沙箱影响）
    for adapter_cls in l2_model_adapters:
        inst = adapter_cls()
        if inst.available():
            registry[inst.name] = inst

    for spec in L2_AGENTS:
        registry[spec["name"]] = CliAgentAdapter(
            spec["name"], spec["command"],
            timeout_s=spec["timeout_s"], enabled=spec["enabled"],
        )

    if ZEN_AGENT["enabled"]:
        registry[ZEN_AGENT["name"]] = ZenAdapter(
            model=ZEN_AGENT["model"], name=ZEN_AGENT["name"], enabled=True,
        )

    for spec in L1_AGENTS:
        registry[spec["name"]] = LaunchOnlyAdapter(
            spec["name"],
            url_scheme=spec["url"],
            executable=spec["exe"],
            drop_dir=drop_dir,
            enabled=True,
            open_app=False,   # 默认不弹窗；用户在 UI 显式开启
        )

    return registry


def registry_report(registry: dict[str, PeerAdapter]) -> list[dict[str, Any]]:
    return [adapter.describe() for adapter in registry.values()]
