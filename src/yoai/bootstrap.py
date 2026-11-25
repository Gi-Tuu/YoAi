"""YoAi 桌面 runtime 的 agent 组装层（不依赖任何 UI 框架）。

从旧 PySide6 端 yoai/desktop/app.py 提取——Tauri runtime 与未来宿主共用。
只组装 YoAiAgent，不改内核。
"""

from __future__ import annotations

import os
from pathlib import Path


def agent_kwargs(data_dir=None, *, channel=None, auto_approve: bool = False) -> dict:
    """桌面端 agent 构造参数：实操工具默认开，YOAI_BUILTIN_TOOLS=0 可关。

    会话里的 agent 由 SessionManager 创建，必须在这里显式传——
    只在外层构造处传对 session 路径无效（2026-11-24 实测 bug）。
    """
    enable = os.environ.get("YOAI_BUILTIN_TOOLS", "1") != "0"
    kwargs = {"builtin_tools": enable}
    if data_dir is not None and enable:
        kwargs["workspace_root"] = Path(data_dir) / "workspace"
    # 只读挂载扩展目录（AI 调试宿主项目用）：YOAI_READONLY_ROOTS，路径分隔符
    # 用 os.pathsep（Windows 是分号）。默认不挂载，行为与旧版一致。
    readonly_raw = os.environ.get("YOAI_READONLY_ROOTS", "").strip()
    if readonly_raw and enable:
        roots = [r for r in (s.strip() for s in readonly_raw.split(os.pathsep)) if r]
        if roots:
            kwargs["readonly_roots"] = roots

    # 权限档位（Core 三档 allow_all / auto / deny_all）：
    # - 默认 auto：白名单内放行，文件写等白名单外工具弹窗确认
    # - YOAI_PERMISSION_MODE=allow_all：全部自动放行，不弹窗（临时测试/信任环境）
    # - 无头自检强制 allow_all：无人点弹窗
    from yai_core.policy import AllowlistPolicy
    env_mode = os.environ.get("YOAI_PERMISSION_MODE", "").strip().lower()
    if auto_approve or env_mode == "allow_all":
        kwargs["policy"] = AllowlistPolicy(mode="allow_all")
        return kwargs
    readonly_and_internal = {
        "all_topics", "events_between", "facts_by_tag", "list_facts", "list_goals",
        "recall_fact", "related_events", "summarize_theme",
        "file_list", "file_read", "web_search", "web_fetch", "open_url",
        "remember_event", "remember_fact", "create_goal", "complete_goal",
        "now", "recent_events", "list_tools",
        "file_ro_list", "file_ro_read",
        # forget_fact / forget_event 是删除操作、shell_run 可执行命令：
        # 不进白名单，auto 档每次弹窗确认（默认拒绝）
    }
    kwargs["policy"] = AllowlistPolicy(allowed=readonly_and_internal, mode="auto")
    if channel is not None:
        kwargs["channel"] = channel
    return kwargs


def build_main_model(data_dir=None):
    """主对话模型：真实网关优先，不可用时降级 DemoModel（离线可跑）。

    返回 (provider, archive)：archive 供证据记录 expert 身份与父节点对照。
    """
    from yoai.demo_model import DemoModel
    from yoai.models import (
        SuanliAdapter, GatewayModelProvider, ExpertModelProvider,
    )
    from yoai.models.core_anthropic_provider import (
        CoreAnthropicModelProvider, core_anthropic_available,
    )
    from yoai.evolution import EvolutionArchive, ExpertRouter, ExpertSpec

    base = None
    adapter = SuanliAdapter()
    if adapter.available():
        # OpenAI 兼容网关：仍走自写适配器桥接
        base = GatewayModelProvider(adapter)
    elif core_anthropic_available():
        # Anthropic 兼容网关（DeepSeek）：走 Core 官方 AnthropicProvider。
        # 协议翻译/thinking 回传/prompt cache 由 Core 维护；异常降级与
        # stall 重试由 CoreAnthropicModelProvider 包装保留（2026-11-24 迁移）。
        base = CoreAnthropicModelProvider()
    if base is None:
        base = DemoModel()

    # 进化档案 + 节能路由：给主对话一个"谁执行"的真实决策
    from yoai.agent import _default_data_dir
    archive = EvolutionArchive(
        (data_dir or _default_data_dir()) / "evolution" / "evolution.json",
        dependencies={"yoai": "phase1.5"},
    )
    if archive.root is None:
        archive.create_root("通用根", ExpertSpec())
    router = ExpertRouter(archive)
    return ExpertModelProvider(base, router, archive), archive


def resolve_model_name(provider) -> str:
    """从 provider 包装链解析可读模型名（穿透 .base / .adapter 多层包装）。"""
    base = provider
    for _ in range(5):
        nxt = getattr(base, "base", None) or getattr(base, "adapter", None)
        if nxt is None or nxt is base:
            break
        base = nxt
    model = ""
    if hasattr(base, "_config"):
        try:
            model = str(base._config()[2])
        except Exception:  # noqa: BLE001
            model = ""
    if not model:
        model = ("离线 Demo" if type(base).__name__ == "DemoModel"
                 else getattr(base, "name", type(base).__name__))
    return model


def clean_final_text(text: str) -> str:
    """清理最终回复里的 <tool_output> 内嵌块（旧端主窗口逻辑）。"""
    import html as _html
    import re

    def replace_tool_output(match: re.Match) -> str:
        inner = re.sub(r"<[^>]+>", "", match.group(1))
        return _html.unescape(inner).strip()

    cleaned = re.sub(
        r"<tool_output\b[^>]*>(.*?)</tool_output>",
        replace_tool_output,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
