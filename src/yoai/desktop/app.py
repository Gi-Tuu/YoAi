"""YoAi 桌面 APP 入口。

启动（用 Core venv，已装 PySide6）：
    QT_QPA_PLATFORM=offscreen python -m yoai.desktop.app   # 无头验证
    python -m yoai.desktop.app                             # 真实窗口

打包成 exe 后支持：
    YoAi.exe --self-check   # 构建自检：初始化+渲染窗口+写标记文件后退出，不弹窗
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _agent_kwargs(data_dir=None, *, channel=None, auto_approve: bool = False) -> dict:
    """桌面端 agent 构造参数：实操工具默认开，YOAI_BUILTIN_TOOLS=0 可关。

    会话里的 agent 由 SessionManager 创建，必须在这里显式传——
    只在 main_window 的直接构造里传对 session 路径无效（2026-11-24 实测 bug）。
    """
    enable = os.environ.get("YOAI_BUILTIN_TOOLS", "1") != "0"
    kwargs = {"builtin_tools": enable}
    if data_dir is not None and enable:
        kwargs["workspace_root"] = Path(data_dir) / "workspace"

    # 权限档位（Core 三档 allow_all / auto / deny_all）：
    # - 默认 auto：白名单内放行，文件写等白名单外工具弹窗确认
    # - YOAI_PERMISSION_MODE=allow_all：全部自动放行，不弹窗（临时测试/信任环境）
    # - self-check 强制 allow_all：无人点弹窗
    from yai_core.policy import AllowlistPolicy
    env_mode = os.environ.get("YOAI_PERMISSION_MODE", "").strip().lower()
    if auto_approve or env_mode == "allow_all":
        kwargs["policy"] = AllowlistPolicy(mode="allow_all")
        return kwargs
    readonly_and_internal = {
        "all_topics", "events_between", "facts_by_tag", "list_facts", "list_goals",
        "recall_fact", "related_events", "summarize_theme",
        "file_list", "file_read", "web_search", "web_fetch",
        "remember_event", "remember_fact", "create_goal", "complete_goal",
    }
    kwargs["policy"] = AllowlistPolicy(allowed=readonly_and_internal, mode="auto")
    if channel is not None:
        kwargs["channel"] = channel
    return kwargs


def _self_check() -> int:
    """exe 自检：走完窗口构建与一次真实工具闭环，写标记文件后退出。

    用于在无控制台的 windowed exe 上确认内部逻辑真的跑通（stdout 不可见）。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from yoai.agent import YoAiAgent, _default_data_dir
    from yoai.adapters import build_registry
    from yoai.demo_model import DemoModel
    from yoai.demo_world import build_demo_channel
    from yoai.desktop.main_window import MainWindow
    from yoai.session import SessionManager
    from yoai.evidence import EvidenceStore
    from yoai.models import ExpertModelProvider
    from yoai.evolution import EvolutionArchive, ExpertRouter, ExpertSpec

    app = QApplication.instance() or QApplication([])
    data_dir = _default_data_dir()
    evidence_store = EvidenceStore(data_dir / "evidence" / "evidence.json")

    # 自检也走完整专家路由链路（用 DemoModel 保离线），验证 expert_id 真落证据
    evo_archive = EvolutionArchive(data_dir / "evolution" / "evolution.json")
    if evo_archive.root is None:
        evo_archive.create_root("通用根", ExpertSpec())

    def selfcheck_model():
        return ExpertModelProvider(DemoModel(), ExpertRouter(evo_archive), evo_archive)

    sessions = SessionManager(data_dir / "sessions", model_factory=selfcheck_model,
                              agent_kwargs=_agent_kwargs(data_dir, auto_approve=True))
    if not sessions.list_sessions():
        sessions.create("自检会话")
    agent = sessions.current_agent()
    channel = build_demo_channel(data_dir / "chat")
    registry = build_registry(data_dir / "drops")
    win = MainWindow(
        agent, channel=channel, registry=registry,
        session_manager=sessions, evidence_store=evidence_store,
        evolution_archive=evo_archive,
    )

    results: dict[str, object] = {
        "window_title": win.windowTitle(),
        "tools": agent.list_tools(),
        "tabs": [win.tabs.tabText(i) for i in range(win.tabs.count())],
        "theme": win.palette.name,
        "galaxy_planets": len(win.galaxy.field.planets) if win.galaxy else 0,
        "chat_peers": list(channel.peers.keys()),
        "chat_groups": [g.name for g in channel.groups()],
        "external_agents": len(registry),
        "external_l2": [n for n, a in registry.items() if a.level == "L2"],
        "session_count": len(sessions.list_sessions()),
        "session_id": sessions.current.id if sessions.current else "",
    }
    win.show()
    app.processEvents()

    # 跑一次真实任务闭环
    win.input.setText("记住我偏好深色主题")
    win._on_send()
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(8000)
    if win.worker is not None and win.worker.isRunning():
        win.worker.task_done.connect(lambda _: loop.quit())
        loop.exec()
    timer.stop()

    results["facts_after_task"] = agent.context.count()
    results["chat_has_reply"] = "[YoAi]" in win.chat.toPlainText()
    results["session_history_len"] = sessions.history_len()
    results["evidence_count"] = evidence_store.count()
    results["evidence_status"] = evidence_store.status()
    results["expert_id"] = getattr(agent.model, "last_expert_id", None) if hasattr(agent, "model") else None
    results["route_reason"] = (
        agent.model.last_decision.reason
        if hasattr(agent, "model") and getattr(agent.model, "last_decision", None) else ""
    )
    results["verification_enabled"] = agent.core.outcome_verifier is not None
    latest = evidence_store.latest()
    results["verification_status"] = (
        latest.verification.get("status") if latest and latest.verification else None
    )

    # M2 引擎冒烟：对最新证据跑一次进化决策（自检数据少，预期不晋升，验证门控生效）
    try:
        from yoai.evolution import EvolutionEngine
        engine = EvolutionEngine(evo_archive, evidence_store)
        if latest is not None:
            evo_report = engine.evolve(latest.id)
            results["evolution_triggered"] = evo_report.triggered
            results["evolution_cause"] = evo_report.cause
            results["evolution_promoted"] = (
                evo_report.promotion.promoted if evo_report.promotion else False
            )
        results["evolution_nodes"] = evo_archive.count()
    except Exception as exc:  # noqa: BLE001 - 自检旁路不阻断
        results["evolution_error"] = f"{type(exc).__name__}: {exc}"

    # 通讯闭环自检：在群里发消息，确认收到多个 peer 的回复
    import asyncio
    from yoai.chat import Message

    group_id = channel.groups()[0].id
    produced = asyncio.run(channel.send(Message.create("user", group_id, "大家好")))
    replies = [m for m in produced if m.kind == "reply"]
    results["chat_group_replies"] = len(replies)

    import json
    # 标记写进 agent 的数据目录（源码模式=项目 output/，exe 模式=exe 同目录 output/）
    marker = data_dir / "selfcheck.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SELFCHECK_OK", results, flush=True)
    return 0


def _build_main_model(data_dir=None):
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
    archive = EvolutionArchive(
        (data_dir or _default_data_dir()) / "evolution" / "evolution.json",
        dependencies={"yoai": "phase1.5"},
    )
    if archive.root is None:
        archive.create_root("通用根", ExpertSpec())
    router = ExpertRouter(archive)
    return ExpertModelProvider(base, router, archive), archive


def main() -> int:
    if "--self-check" in sys.argv:
        return _self_check()

    from PySide6.QtWidgets import QApplication

    from yoai.adapters import build_registry
    from yoai.demo_world import build_demo_channel
    from yoai.desktop.main_window import MainWindow
    from yoai.session import SessionManager
    from yoai.agent import _default_data_dir
    from yoai.evidence import EvidenceStore

    app = QApplication.instance() or QApplication(sys.argv)

    # 单实例守卫：已有桌面实例在跑时，第二个启动直接退出（self-check 除外）。
    # 必须保活到进程结束——guard 被 GC 会释放 server，第二实例就能起来了。
    from yoai.desktop.single_instance import SingleInstanceGuard
    guard = SingleInstanceGuard()
    if not guard.acquire():
        print("YoAi 已在运行（单实例模式），本次启动已退出。", flush=True)
        return 0
    app._yoai_instance_guard = guard   # 保活引用，随 QApplication 生命周期

    data_dir = _default_data_dir()

    # 证据基础设施：每次对话自动采集真事件 → 落盘 → 归因
    evidence_store = EvidenceStore(data_dir / "evidence" / "evidence.json")

    # 会话管理：每个 session 独立持久化历史，切换继续，不再每次新建
    def model_factory():
        provider, _ = _build_main_model(data_dir)
        return provider

    # 审批通道：Core 的 auto 权限档遇到文件写等白名单外工具时弹窗等用户确认。
    # 必须在建 agent 前创建——Core 在 AgentCore 构造时绑定 channel。
    from yoai.desktop.approval import ApprovalChannel
    approval = ApprovalChannel()
    app._yoai_approval = approval   # 保活

    sessions = SessionManager(data_dir / "sessions", model_factory=model_factory,
                              agent_kwargs=_agent_kwargs(data_dir, channel=approval))
    if not sessions.list_sessions():
        sessions.create("新会话")
    agent = sessions.current_agent()

    channel = build_demo_channel(data_dir / "chat")
    registry = build_registry(data_dir / "drops")
    # 星系图用的档案（与路由共用同一份持久化文件）
    from yoai.evolution import EvolutionArchive, ExpertSpec
    archive = EvolutionArchive(data_dir / "evolution" / "evolution.json")
    if archive.root is None:
        archive.create_root("通用根", ExpertSpec())
    window = MainWindow(
        agent, channel=channel, registry=registry,
        session_manager=sessions, evidence_store=evidence_store,
        evolution_archive=archive, approval_channel=approval,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
