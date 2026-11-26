"""YoAi Desktop Runtime — Tauri ↔ YoAiAgent 的 JSONL IPC 桥。

职责边界（严格）：
- **不改内核**：只组装 YoAiAgent（复用 yoai.bootstrap 语义），消费 astream
  事件流，翻译成协议消息；Agent Loop / 工具 / 适配器零改动。
- **事件只用现有公开信息**：Core EventType + YoAi 的 thinking/delta。
- **进程生命周期**：stdin 读命令、stdout 只写协议行、stderr 写日志；
  shutdown 取消全部任务后退出。

启动（开发模式）：
    python apps/desktop-tauri/runtime/yoai_runtime.py

PYTHONPATH 需含 yoai 的 src 与 Core 的 src（脚本内会自动探测常见位置兜底）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# --- 路径自举：兼容三种部署位置 ---
#  A) 源码树 apps/desktop-tauri/runtime/ → parents[3] = YoAi 根
#  B) 打包/执行目录 dist/runtime/       → parents[2] = YoAi 根
# 另外支持 YOAI_SRC / YAI_CORE_SRC 环境变量显式指定（脱离源码树部署时用）。
def _core_src_candidates() -> list[str]:
    """YAI_CORE_SRC 指向 Core 根目录；yai_core 可能在根/src 下，做两级探测。"""
    env = os.environ.get("YAI_CORE_SRC", "")
    if not env:
        return []
    root = Path(env)
    if (root / "yai_core").is_dir():
        return [str(root)]
    if (root / "src" / "yai_core").is_dir():
        return [str(root / "src")]
    return []


_HERE = Path(__file__).resolve()

# 生产环境 YAI_CORE_SRC 可能指向 Core/src（而不是 Core 根）。SuanliAdapter 用
# YAI_CORE_SRC 直接拼 .env 路径，指到 src 就读不到讯飞网关配置、会错误降级到
# Anthropic DeepSeek。这里在 import 任何 yoai 模块之前把它规范成 Core 根。
_env_core = os.environ.get("YAI_CORE_SRC", "").strip()
if _env_core:
    p = Path(_env_core).expanduser()
    if (p / "yai_core").is_dir() and (p.parent / ".env").is_file():
        os.environ["YAI_CORE_SRC"] = str(p.parent)

_candidates = [
    os.environ.get("YOAI_SRC", ""),      # 显式：YoAi 根（其下有 src/yoai）
    str(_HERE.parents[3] / "src"),       # A) apps/desktop-tauri/runtime → 根/src
    str(_HERE.parents[2] / "src"),       # B) dist/runtime → 根/src
    *_core_src_candidates(),             # Core 源码（yai_core 包所在）
]
for _p in _candidates:
    if _p and Path(_p).is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from protocol import (  # noqa: E402  (自举后导入)
    PROTOCOL_VERSION, Seq, approval_recorded, approval_request, archive_state,
    attachment_ready, boundary_state, browser_opened, chat_msg, chat_state,
    encode, error, event, file_changed, file_content, file_tree, final,
    evolution_report, feedback_recorded, message_updated, permission_state,
    ready, rsi_promoted, rsi_rolled_back, rsi_triggered, rsi_validated,
    share_exported, snapshot, status, trial_report, trial_state,
)


def _data_dir() -> Path:
    """数据目录（对齐旧端便携语义：exe/runtime 同级的 output）。

    优先级：① 宿主显式传 YOAI_DATA_DIR；② dist/runtime → dist/output（旧端
    数据连续性）；③ yoai.agent._default_data_dir()（源码开发态=项目根/output）。
    """
    env = os.environ.get("YOAI_DATA_DIR", "").strip()
    if env:
        path = Path(env).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    sibling = _HERE.parent.parent / "output"
    if _HERE.parent.name == "runtime" and sibling.is_dir():
        return sibling
    from yoai.agent import _default_data_dir
    return _default_data_dir()


def _log(msg: str) -> None:
    """日志只走 stderr，stdout 保持协议纯净。"""
    print(f"[yoai-runtime] {msg}", file=sys.stderr, flush=True)


class Runtime:
    def __init__(self) -> None:
        self.seq = Seq()
        self.agent: Any = None
        self.model_id = ""
        self.model_options: dict[str, str] = {}
        self.sessions: Any = None
        self.channel: Any = None          # peer 通讯（通讯页）
        self.registry: dict[str, Any] = {}  # 外部智能体注册表
        self.evidence_store: Any = None   # 证据落盘（旁路）
        self.tasks: dict[str, asyncio.Task] = {}       # run_id -> task
        self.chat_tasks: dict[str, asyncio.Task] = {}  # target -> 投递任务
        self.running: dict[str, tuple[str, str]] = {}  # run_id -> (task_id, cancelled?)
        self.pending_approvals: dict[str, asyncio.Future] = {}
        self.stream_text: dict[str, str] = {}  # run_id -> 累积流式文本（final 空时兜底）
        self.think_buffer: dict[str, str] = {}  # run_id -> 累积 thinking（落盘用）
        self.thinking_store: Any = None
        self.projects: Any = None          # ProjectStore（项目模式）
        self.file_changes: Any = None      # FileChangeStore（产物/改动记录）
        self.actions: Any = None           # ConversationActions（撤回/编辑覆盖层）
        self.attachments: Any = None       # 附件目录根
        self.evolution_reports: Any = None # EvolutionReportStore（显式进化审计）
        self.feedback_store: Any = None    # FeedbackStore（R0 用户反馈信号）
        self.trial_store: Any = None       # TrialStore（R3.2 试用批次）
        self.mcp_manager: Any = None       # McpManager（标准 MCP 客户端）
        self.router: Any = None            # ExpertRouter（trial scope 覆盖）
        self.run_evidence: dict[str, str] = {}  # run_id -> evidence_id（反馈绑定用）
        self._write_lock = asyncio.Lock()

    # ---- 输出 ----
    async def send(self, msg: dict[str, Any]) -> None:
        async with self._write_lock:
            sys.stdout.write(encode(msg))
            sys.stdout.flush()

    # ---- 构造 agent（复用桌面生产语义，不改内核）----
    def _ensure_agent(self) -> None:
        if self.agent is not None:
            return
        from yoai.bootstrap import agent_kwargs, available_main_models, build_main_model
        from yoai.user_config import UserConfig
        from yoai.session import SessionManager
        from yoai.project import ProjectStore
        from yoai.file_changes import FileChangeStore
        from yoai.conversation_actions import ConversationActions, ConversationMemory
        from yai_core_sidecar_channel import make_sidecar_channel  # 本目录辅助

        data_dir = _data_dir()
        self.projects = ProjectStore(data_dir / "projects")
        self.file_changes = FileChangeStore(data_dir)
        self.actions = ConversationActions(data_dir)
        self.attachments = data_dir / "attachments"
        from yoai.evolution import EvolutionReportStore, TrialStore
        from yoai.evidence import FeedbackStore
        self.evolution_reports = EvolutionReportStore(data_dir)
        self.feedback_store = FeedbackStore(data_dir)
        self.trial_store = TrialStore(data_dir)
        from yoai.mcp import McpManager
        self.mcp_manager = McpManager(data_dir)
        channel_cb = make_sidecar_channel(self._request_host)
        self.model_options = available_main_models()
        preferred = UserConfig(data_dir).load().get("desktop_model")
        self.model_id = preferred if isinstance(preferred, str) and preferred in self.model_options else next(iter(self.model_options))
        provider, _archive = build_main_model(data_dir, model_id=self.model_id)
        self.router = getattr(provider, "router", None)
        agent_kwargs_base = agent_kwargs(data_dir, channel=channel_cb)
        agent_kwargs_base["mcp_manager"] = self.mcp_manager
        def kwargs_for_session(session: Any) -> dict[str, Any] | None:
            """项目模式：给该会话的 agent 挂项目读写工具；聊天模式返回 None 用默认。"""
            if getattr(session, "mode", "chat") != "project":
                return None
            proj = self.projects.get(getattr(session, "project_id", ""))
            if proj is None:
                return None
            return {
                "project_root": proj.path,
                "project_name": proj.name,
                "file_change_store": self.file_changes,
                "change_context": {"session_id": session.id, "project_id": proj.id},
            }

        def memory_dir_for_session(session: Any) -> Path | None:
            """项目模式：记忆按项目隔离；聊天模式用全局共享目录。"""
            if getattr(session, "mode", "chat") != "project":
                return None
            pid = getattr(session, "project_id", "")
            return data_dir / "projects" / pid / "memory" if pid else None

        self.sessions = SessionManager(
            data_dir / "sessions",
            model_factory=lambda: provider,
            agent_kwargs=agent_kwargs_base,
            agent_kwargs_for_session=kwargs_for_session,
            memory_dir_for_session=memory_dir_for_session,
            memory_for_session=lambda sid, store: ConversationMemory(store, self.actions, sid),
        )
        # 首次启动（数据目录为空）必须建初始会话——旧端 app.py main() 语义，
        # 否则 current_agent() 会 KeyError，新用户第一句话就失败。
        if not self.sessions.list_sessions():
            self.sessions.create("新会话")
        self.agent = self.sessions.current_agent()

        # thinking 持久化（YoAi 侧，内核零改动）：历史消息也能看思考过程
        try:
            from yoai.thinking_store import ThinkingStore
            self.thinking_store = ThinkingStore(data_dir)
        except Exception as exc:  # noqa: BLE001
            _log(f"thinking store init failed: {exc}")
            self.thinking_store = None

        # 通讯基础设施（旧端 build_demo_channel / build_registry 语义）
        from yoai.adapters import build_registry
        from yoai.demo_world import build_demo_channel
        self.channel = build_demo_channel(data_dir / "chat")
        self.registry = build_registry(data_dir / "drops")

        # 证据落盘（旧端 worker.py 旁路语义：失败不影响任务）
        try:
            from yoai.evidence import EvidenceStore
            self.evidence_store = EvidenceStore(data_dir / "evidence" / "evidence.json")
        except Exception as exc:  # noqa: BLE001
            _log(f"evidence store init failed: {exc}")
            self.evidence_store = None

    async def _request_host(self, kind: str, payload: dict[str, Any]) -> Any:
        """SidecarChannel 回调：把审批/澄清发到前端并等待回答。"""
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        key = f"{kind}:{id(fut)}"
        self.pending_approvals[key] = fut
        if kind == "approval/request":
            task_id = self._current_task_id()
            run_id = self._current_run_id()
            seq = self.seq.for_run(task_id, run_id)
            tool = str(payload.get("tool", ""))
            reason = str(payload.get("prompt", "") or payload.get("reason", ""))
            await self.send(approval_request(
                task_id, run_id, seq, tool,
                reason or "确认执行该操作？",
                json.dumps(payload, ensure_ascii=False)[:800],
            ))
        # clarify 走通用 event，前端用输入框回 reply
        elif kind == "clarify/request":
            await self.send(event(
                self._current_task_id(), self._current_run_id(),
                self.seq.for_run(self._current_task_id(), self._current_run_id()),
                "clarify_requested", payload,
            ))
        try:
            return await fut
        finally:
            self.pending_approvals.pop(key, None)

    def _current_task_id(self) -> str:
        return getattr(self, "_active_task_id", "")

    def _current_run_id(self) -> str:
        return getattr(self, "_active_run_id", "")

    # ---- 状态快照（旧端侧栏卡片 + 会话管理的数据源）----
    def _model_name(self) -> str:
        try:
            from yoai.bootstrap import resolve_model_name
            return resolve_model_name(getattr(self.agent, "model", None) or self.agent)
        except Exception:  # noqa: BLE001
            return "未知"

    def _snapshot(self) -> dict[str, Any]:
        from yoai.bootstrap import clean_final_text
        from yai_core.kernel.context import Context
        context = Context("")
        sessions = [s.to_dict() for s in self.sessions.list_sessions()]
        current = self.sessions.current
        history: list[dict[str, Any]] = []
        try:
            memory = self.agent.core.memory
            pairs = (memory.history_with_indices() if hasattr(memory, "history_with_indices")
                     else list(enumerate(memory.history())))
            messages = [m for _, m in pairs]
            timestamps = self.sessions.history_timestamps(current.id, messages) if current else []
            for pos, (index, message) in enumerate(pairs):
                context.add(message)
                role = getattr(message, "role", "")
                if role not in ("user", "assistant"):
                    continue
                content = getattr(message, "content", "")
                if isinstance(content, list):
                    content = " ".join(
                        str(part.get("text", "")) for part in content
                        if isinstance(part, dict)
                    )
                if role == "assistant":
                    content = clean_final_text(str(content))
                item = {"role": role, "text": str(content), "idx": index}
                if timestamps and pos < len(timestamps):
                    item["at"] = timestamps[pos]
                history.append(item)
        except Exception as exc:  # noqa: BLE001
            _log(f"history load failed: {exc}")
        facts: dict[str, str] = {}
        try:
            facts = {str(k): str(v) for k, v in self.agent.context.list_all().items()}
        except Exception:  # noqa: BLE001
            pass
        goals: list[dict[str, Any]] = []
        try:
            goals = [dict(g) for g in self.agent.goals.list_goals()]
        except Exception:  # noqa: BLE001
            pass
        write_stats: dict[str, int] = {}
        try:
            write_stats = {k: int(v) for k, v in self.agent.last_write_stats().items()}
        except Exception:  # noqa: BLE001
            pass
        tools: list[str] = []
        try:
            tools = [str(t) for t in self.agent.list_tools()]
        except Exception:  # noqa: BLE001
            pass
        thinking_log: list[dict[str, Any]] = []
        if self.thinking_store is not None and current:
            try:
                thinking_log = self.thinking_store.load(current.id)
            except Exception:  # noqa: BLE001
                pass
        state = snapshot(
            sessions=sessions,
            current_id=current.id if current else "",
            history=history,
            model=self._model_name(),
            facts=facts,
            goals=goals,
            write_stats=write_stats,
            tools=tools,
            thinking_log=thinking_log,
            projects=self.projects.to_list() if self.projects is not None else [],
            **(self.file_changes.summary(
                session_id=self._session_id(),
                project_id=getattr(current, "project_id", "") if current else "",
            ) if self.file_changes is not None else {"artifacts": [], "changes": []}),
        )

        state["model_id"] = self.model_id
        state["model_options"] = [{"id": key, "label": label} for key, label in self.model_options.items()]
        state["context_usage"] = {"used": min(context.total_chars(), context.max_chars), "limit": context.max_chars}
        return state

    async def _select_model(self, model_id: str) -> None:
        from yoai.bootstrap import build_main_model
        from yoai.user_config import UserConfig

        self._ensure_agent()
        if model_id not in self.model_options or any(not task.done() for task in self.tasks.values()):
            await self.send(error("protocol", "模型不可用或任务仍在执行"))
            return
        if model_id == self.model_id:
            return
        data_dir = _data_dir()
        provider, _archive = build_main_model(data_dir, model_id=model_id)
        UserConfig(data_dir).save({"desktop_model": model_id})
        self.sessions.replace_model_factory(lambda: provider)
        self.agent = self.sessions.current_agent()
        self.model_id = model_id
        await self._push_snapshot()
        await self._push_permission_state()

    def _session_id(self) -> str:
        current = getattr(self.sessions, "current", None) if self.sessions else None
        return str(current.id) if current else ""

    def _file_root(self) -> tuple[Path, str]:
        """文件面板根目录：项目会话=项目文件夹；聊天会话=data_dir/workspace。

        与项目工具同一套越界防护（resolve_in_project），面板只读，不发放写能力。
        """
        current = getattr(self.sessions, "current", None) if self.sessions else None
        if current is not None and getattr(current, "mode", "chat") == "project":
            proj = self.projects.get(getattr(current, "project_id", "")) if self.projects else None
            if proj is not None:
                return Path(proj.path).resolve(), f"项目 · {proj.name}"
        root = _data_dir() / "workspace"
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve(), "工作区"

    def _agents_clear(self) -> None:
        """清空会话 agent 缓存（项目变更/删除后必须重建，否则工具集是旧的）。"""
        if self.sessions is not None and hasattr(self.sessions, "_agents"):
            self.sessions._agents.clear()

    def _sync_permission_for_session(self, agent: Any = None, *, is_new: bool = False) -> str:
        """把指定 agent 的 policy 设为「该会话自己的」档位，返回档位名。

        按会话独立：每个 session 首次使用时把初始档位固化为自己的，
        之后各会话改档互不影响。is_new=True 时初始值取全局默认（不继承上一会话）。
        """
        from yoai.bootstrap import apply_permission_level, permission_level_of
        from yoai.user_config import UserConfig

        target = agent if agent is not None else self.agent
        policy = getattr(getattr(target, "core", None), "policy", None)
        if policy is None:
            return ""
        # 防止改到 SessionManager 共享的 policy 模板（新会话会继承）
        import copy as _copy
        policy = _copy.copy(policy)
        target.core.policy = policy
        executor = getattr(target.core, "executor", None)
        if executor is not None:
            executor.policy = policy
        cfg = UserConfig(_data_dir())
        sid = self._session_id()
        if not sid:
            return permission_level_of(policy)
        level = cfg.permission_level(sid)
        if not level:
            # 未存过：优先全局默认；没有全局默认时用当前 policy（由环境变量/
            # 构造参数决定）作为初始值。create 时 agent 是全新的，policy 本就
            # 是环境默认，不会继承另一个会话改过的档位。
            level = cfg.default_level() or permission_level_of(policy) or "smart"
            cfg.apply_default_to(sid, level)
        apply_permission_level(policy, level)
        return level

    async def _push_permission_state(self) -> None:
        """推当前会话的权限档位给前端（UI 控件显示）。"""
        from yoai.bootstrap import permission_level_of
        from yoai.user_config import UserConfig
        level = self._sync_permission_for_session()
        if not level:
            level = permission_level_of(
                getattr(getattr(self.agent, "core", None), "policy", None)) or \
                UserConfig(_data_dir()).default_level() or "smart"
        descriptions = {
            "full": "允许完全访问：所有工具自动执行，不弹窗",
            "smart": "智能访问：只读/记忆类自动放行，写操作弹窗确认",
            "manual": "手批访问：每个工具调用都弹窗确认",
        }
        await self.send(permission_state(
            level=level, description=descriptions.get(level, "")))

    async def _push_snapshot(self) -> None:
        await self.send(self._snapshot())

    # ---- 通讯页 ----
    def _chat_state(self) -> dict[str, Any]:
        conversations: list[dict[str, Any]] = []
        try:
            for peer in self.channel.peers.values():
                conversations.append({
                    "id": peer.id, "name": peer.name, "kind": "peer",
                    "members": 1,
                })
            for group in self.channel.groups():
                conversations.append({
                    "id": group.id, "name": group.name, "kind": "group",
                    "members": len(group.members),
                })
        except Exception as exc:  # noqa: BLE001
            _log(f"chat state failed: {exc}")
        external: list[dict[str, Any]] = []
        for name, adapter in self.registry.items():
            try:
                desc = adapter.describe()
                external.append({
                    "name": name, "level": str(desc.get("level", "")),
                    "available": bool(desc.get("available", False)),
                })
            except Exception:  # noqa: BLE001
                external.append({"name": name, "level": "?", "available": False})
        return chat_state(conversations=conversations, external=external)

    def _chat_history(self, target: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            for m in self.channel.history(target):
                own = m.sender == "user"
                out.append({
                    "sender": str(m.sender),
                    "name": "我" if own else str(m.meta.get("peer_name", m.sender)),
                    "content": str(m.content),
                    "own": own,
                })
        except Exception as exc:  # noqa: BLE001
            _log(f"chat history failed: {exc}")
        return out

    async def _push_chat_state(self) -> None:
        state = self._chat_state()
        state["history_target"] = ""
        await self.send(state)

    def _register_external(self, name: str) -> str:
        """双击外部智能体：注册为 peer（幂等），返回 peer_id。"""
        from yoai.adapters import ExternalPeer
        adapter = self.registry.get(name)
        if adapter is None:
            return ""
        peer_id = f"ext-{name}"
        if peer_id not in self.channel.peers:
            self.channel.register(ExternalPeer(peer_id, adapter))
        return peer_id

    async def _chat_send(self, target: str, text: str) -> None:
        """群/单聊投递：复用 channel.send，回复逐条推给前端。"""
        from yoai.chat import Message
        try:
            message = Message.create("user", target, text)
            produced = await self.channel.send(message)
            for m in produced or []:
                if m.sender == "user":
                    continue
                await self.send(chat_msg(
                    target=target, sender=str(m.sender),
                    name=str(m.meta.get("peer_name", m.sender)),
                    content=str(m.content), own=False,
                ))
        except Exception as exc:  # noqa: BLE001
            await self.send(chat_msg(
                target=target, sender="system", name="系统",
                content=f"发送失败：{type(exc).__name__}: {exc}", own=False,
            ))
        finally:
            self.chat_tasks.pop(target, None)

    # ---- 星图 ----
    def _archive_state(self) -> dict[str, Any]:
        from yoai.evolution import EvolutionArchive

        archive = EvolutionArchive(
            _data_dir() / "evolution" / "evolution.json")
        nodes: list[dict[str, Any]] = []
        by_id: dict[str, Any] = {}
        for node in archive.list_nodes():
            by_id[node.id] = node
        for node in archive.list_nodes():
            depth, cur, seen = 0, node, set()
            while cur.parent_id and cur.id not in seen:
                seen.add(cur.id)
                parent = by_id.get(cur.parent_id)
                if parent is None:
                    break
                depth += 1
                cur = parent
            nodes.append({
                "id": node.id, "name": node.name,
                "lifecycle": str(node.lifecycle),
                "version": int(getattr(node, "version", 1)),
                "parent_id": node.parent_id or "",
                "depth": depth,
                "capability_tags": list(getattr(node.spec, "capability_tags", []) or []),
                "tools": list(getattr(node.spec, "tools", []) or []),
                "strategy_bias": str(getattr(node.spec, "strategy_bias", "") or ""),
                "model_tier": str(getattr(node.spec, "model_tier", "") or ""),
                "diff": str(getattr(node, "diff", "") or ""),
                "evidence_count": len(getattr(node, "evidence", []) or []),
                "evidence": [e.to_dict() if hasattr(e, "to_dict") else dict(e)
                             for e in (getattr(node, "evidence", []) or [])],
                "reports": (self.evolution_reports.list(node.id)
                            if self.evolution_reports is not None else []),
                "created_at": str(getattr(node, "created_at", "")),
                "prompt_suffix": str(getattr(node.spec, "prompt_suffix", "") or ""),
            })
        return archive_state(nodes=nodes)

    def _trial_for_task(self, task: str):
        if self.trial_store is None:
            return None
        from yoai.evolution.fingerprint import fingerprint
        tags = fingerprint(task).tags
        for record in self.trial_store.list(status="running"):
            if record.scope.startswith("tag:") and record.primary_tag in tags:
                return record
        return None

    async def _run_shadow_parent(self, task: str, trial) -> None:
        """R3.3：同题后台跑 parent，只落 trial 证据，不推 UI、不污染记忆。"""
        if self.evidence_store is None:
            return
        from yai_core.memory import InMemoryStore
        from yoai.agent import YoAiAgent
        from yoai.evidence import ExecutionEvidenceCollector, SAMPLE_TRIAL
        from yoai.evolution import EvolutionArchive, ForcedExpertRouter
        from yoai.evolution.fingerprint import fingerprint as evo_fingerprint
        from yoai.models import ExpertModelProvider

        try:
            archive = EvolutionArchive(_data_dir() / "evolution" / "evolution.json")
            parent = archive.get(trial.parent_id)
            if parent is None:
                return
            base = getattr(self.agent.model, "base", None) or self.agent.model
            forced_router = ForcedExpertRouter(archive, parent.id)
            shadow_provider = ExpertModelProvider(base, forced_router, archive)
            shadow_agent = YoAiAgent(
                model=shadow_provider, data_dir=_data_dir() / "shadow",
                memory=InMemoryStore(), temporal_memory=False,
                builtin_tools=False, outcome_verifier=None,
            )
            collector = ExecutionEvidenceCollector()
            async for event in shadow_agent.astream(task):
                collector.observe(event)
            fp = evo_fingerprint(task)
            evidence = collector.finish(
                session_id=f"shadow-{trial.id}", task=task,
                task_fingerprint=fp.key, fingerprint_tags=fp.tags,
                sample_class=SAMPLE_TRIAL, expert_id=parent.id,
                parent_id=parent.parent_id or "", trial_id=trial.id,
                trial_role="parent",
            )
            self.evidence_store.add(evidence)
        except Exception as exc:  # noqa: BLE001
            _log(f"parent shadow failed: {exc}")

    def _trial_controller(self):
        from yoai.evolution import EvolutionArchive, TrialController
        if (self.evidence_store is None or self.feedback_store is None
                or self.evolution_reports is None or self.trial_store is None):
            raise RuntimeError("RSI 试用存储尚未初始化")
        archive = EvolutionArchive(_data_dir() / "evolution" / "evolution.json")
        return TrialController(archive, self.evidence_store, self.feedback_store,
                               self.evolution_reports, self.trial_store)

    async def _push_boundary_state(self) -> None:
        """RSI R1：把能力边界统计推给看板（只统计，不触发进化）。"""
        from yoai.evidence import build_boundary_report
        if self.evidence_store is None or self.feedback_store is None:
            report = {"window_days": 30, "total": 0, "success": 0,
                      "success_rate": 0.0, "rework": 0, "rework_rate": 0.0, "rows": []}
        else:
            report = build_boundary_report(
                self.evidence_store, self.feedback_store).to_dict()
        await self.send(boundary_state(report=report))

    # ---- 任务执行 ----
    async def start_task(self, task_id: str, run_id: str, user_input: str) -> None:
        try:
            self._ensure_agent()
        except Exception as exc:  # noqa: BLE001
            await self.send(error("startup", f"{type(exc).__name__}: {exc}",
                                  task_id=task_id, run_id=run_id))
            await self.send(status(task_id, run_id, -1, "failed", str(exc)))
            return

        self._active_task_id, self._active_run_id = task_id, run_id
        self.seq.reset_run(task_id, run_id)
        self.stream_text[run_id] = ""
        await self.send(status(task_id, run_id, self.seq.for_run(task_id, run_id),
                               "running"))

        async def _run() -> None:
            # 让文件操作记录带上本轮 run_id（产物/改动卡片按轮次分组）
            ctx = getattr(self.agent, "change_context", None)
            if isinstance(ctx, dict):
                ctx["run_id"] = run_id
            evidence_meta: dict[str, Any] = {}
            try:
                from yoai.evidence import ExecutionEvidenceCollector
                collector = (ExecutionEvidenceCollector()
                             if self.evidence_store is not None else None)
            except Exception:  # noqa: BLE001
                collector = None
            try:
                # 证据元数据（旧端主窗口 evidence_meta 语义）
                try:
                    from yoai.evolution.fingerprint import fingerprint
                    fp = fingerprint(user_input)
                    evidence_meta = {
                        "session_id": self.sessions.current.id if self.sessions.current else "",
                        "task_fingerprint": fp.key,
                        "fingerprint_tags": fp.tags,
                        "sample_class": "evolution",
                        "expert_id": None,
                        "parent_id": None,
                        "model_provider": getattr(self.agent, "model", None),
                    }
                except Exception:  # noqa: BLE001
                    evidence_meta = {}

                trial_for_task = self._trial_for_task(user_input)
                if trial_for_task and evidence_meta:
                    evidence_meta.update({
                        "sample_class": "trial",
                        "expert_id": trial_for_task.node_id,
                        "parent_id": trial_for_task.parent_id,
                        "trial_id": trial_for_task.id,
                        "trial_role": "child",
                    })

                async for ev in self.agent.astream(user_input):
                    name = getattr(ev.type, "value", str(ev.type))
                    data = dict(getattr(ev, "data", {}) or {})
                    seq = self.seq.for_run(task_id, run_id)
                    if collector is not None:
                        collector.observe(ev)
                    if name == "delta":
                        self.stream_text[run_id] = (
                            self.stream_text.get(run_id, "") + str(data.get("text", "")))
                    if name == "thinking":
                        self.think_buffer[run_id] = (
                            self.think_buffer.get(run_id, "") + str(data.get("text", "")))
                    if name == "done":
                        # thinking 落盘（历史消息也能展开查看）
                        think = self.think_buffer.get(run_id, "")
                        if self.thinking_store is not None and think.strip():
                            try:
                                sid = (self.sessions.current.id
                                       if self.sessions and self.sessions.current else "")
                                self.thinking_store.append(
                                    session_id=sid, run_id=run_id,
                                    text=think, user_input=user_input)
                            except Exception as exc:  # noqa: BLE001
                                _log(f"thinking persist failed: {exc}")
                        text = str(data.get("final_text", ""))
                        if not text.strip():
                            # final 空但流式有内容（异常收尾/网关差异）→ 流式兜底
                            text = self.stream_text.get(run_id, "")
                        try:
                            from yoai.bootstrap import clean_final_text
                            text = clean_final_text(text)
                        except Exception:  # noqa: BLE001
                            pass
                        # 本轮的文件操作 → file.changed，前端实时出产物/改动卡片
                        if self.file_changes is not None:
                            try:
                                mine = [r for r in self.file_changes.load(
                                    session_id=self._session_id())
                                    if r.get("run_id") == run_id]
                                for rec in mine:
                                    await self.send(file_changed(
                                        task_id, run_id, self.seq.for_run(task_id, run_id),
                                        record=self.file_changes._public(rec)))
                            except Exception as exc:  # noqa: BLE001
                                _log(f"file.changed push failed: {exc}")
                        await self.send(final(task_id, run_id, seq, text))
                        await self.send(status(task_id, run_id,
                                               self.seq.for_run(task_id, run_id),
                                               "done"))
                        await self._push_snapshot()   # 刷新侧栏（记忆/事实/目标）
                    else:
                        await self.send(event(task_id, run_id, seq, name, data))
            except asyncio.CancelledError:
                await self.send(status(task_id, run_id,
                                       self.seq.for_run(task_id, run_id),
                                       "cancelled"))
                return
            except Exception as exc:  # noqa: BLE001
                await self.send(error("runtime", f"{type(exc).__name__}: {exc}",
                                      task_id=task_id, run_id=run_id))
                await self.send(status(task_id, run_id,
                                       self.seq.for_run(task_id, run_id),
                                       "failed", str(exc)))
                return
            finally:
                self.stream_text.pop(run_id, None)
                self.think_buffer.pop(run_id, None)
            # 证据落盘（旁路，失败不影响任务结果；旧端 worker.py 语义）
            if collector is not None and self.evidence_store is not None:
                try:
                    from yoai.evidence import AttributionEngine
                    meta = evidence_meta
                    provider = meta.get("model_provider")
                    usage_override = (getattr(provider, "total_usage", None)
                                      if provider else None)
                    expert_id = meta.get("expert_id")
                    parent_id = meta.get("parent_id")
                    decision = None
                    if provider is not None and hasattr(provider, "last_decision"):
                        decision = getattr(provider, "last_decision", None)
                        expert_id = getattr(provider, "last_expert_id", None) or expert_id
                        get_parent = getattr(provider, "last_parent_id", None)
                        parent_id = get_parent if get_parent is not None else parent_id
                    evidence = collector.finish(
                        session_id=meta.get("session_id", ""),
                        task=user_input,
                        task_fingerprint=meta.get("task_fingerprint", ""),
                        fingerprint_tags=tuple(meta.get("fingerprint_tags", ())),
                        sample_class=meta.get("sample_class", "evolution"),
                        expert_id=expert_id,
                        parent_id=parent_id,
                        usage_override=usage_override,
                        route_decision=decision.to_dict() if decision else None,
                        trial_id=meta.get("trial_id", ""),
                        trial_role=meta.get("trial_role", ""),
                    )
                    self.evidence_store.add(evidence)
                    self.run_evidence[run_id] = evidence.id
                    if trial_for_task and trial_for_task.id == meta.get("trial_id", ""):
                        await self._run_shadow_parent(user_input, trial_for_task)

                    # R3.3：active 节点每次真实任务后做回归监控，命中则退役回退。
                    if (expert_id and self.feedback_store is not None
                            and self.evolution_reports is not None):
                        from yoai.evolution import EvolutionArchive, RollbackMonitor
                        active_archive = EvolutionArchive(
                            _data_dir() / "evolution" / "evolution.json")
                        active_node = active_archive.get(expert_id)
                        if active_node and active_node.lifecycle == "active":
                            rollback = RollbackMonitor(
                                active_archive, self.evidence_store,
                                self.feedback_store, self.evolution_reports).check(expert_id)
                            if rollback.rolled_back:
                                await self.send(rsi_rolled_back(decision=rollback.to_dict()))
                                await self.send(self._archive_state())

                    attribution = AttributionEngine(self.evidence_store).attribute(evidence)
                    self.evidence_store.add_attribution(attribution)

                    # 显式进化开关：默认关闭，避免每次对话都长分支。
                    # 开启后也只在证据落盘成功后旁路尝试，失败不影响任务结果。
                    if os.environ.get("YOAI_EVOLUTION", "0") == "1":
                        from yoai.evolution import EvolutionArchive, EvolutionEngine
                        archive = EvolutionArchive(_data_dir() / "evolution" / "evolution.json")
                        engine = EvolutionEngine(archive, self.evidence_store)
                        report = engine.evolve(evidence.id)
                        payload = report.to_dict()
                        if self.evolution_reports is not None:
                            self.evolution_reports.add(payload)
                        await self.send(evolution_report(report=payload))
                        await self.send(self._archive_state())
                except Exception as exc:  # noqa: BLE001
                    _log(f"evidence record failed: {exc}")

        task = asyncio.create_task(_run())
        self.tasks[run_id] = task
        task.add_done_callback(lambda _t: self.tasks.pop(run_id, None))

    def cancel_task(self, task_id: str, run_id: str) -> None:
        task = self.tasks.get(run_id)
        if task and not task.done():
            task.cancel()

    # ---- 命令分发 ----
    async def handle(self, cmd: dict[str, Any]) -> bool:
        """返回 False 表示要求退出。"""
        typ = cmd.get("type", "")
        task_id = str(cmd.get("task_id", ""))
        run_id = str(cmd.get("run_id", ""))

        if typ == "hello":
            self._ensure_agent()
            await self.send(ready(tools=[], sessions=[], config={},
                                  python=sys.version.split()[0]))
            await self._push_snapshot()
            await self._push_chat_state()
            await self._push_permission_state()
        elif typ == "task.start":
            await self.start_task(task_id, run_id, str(cmd.get("input", "")))
        elif typ == "task.cancel":
            self.cancel_task(task_id, run_id)
        elif typ == "approval.reply" or typ == "clarify.reply":
            # 找到最早的待回复 future（前端一次只交互一项）
            for key, fut in list(self.pending_approvals.items()):
                if not fut.done():
                    value: Any = cmd.get("allow") if typ == "approval.reply" else cmd.get("answer", "")
                    if typ == "approval.reply":
                        value = bool(cmd.get("allow", False))
                    fut.set_result(value)
                    break
        elif typ in ("session.list", "session.state"):
            await self._push_snapshot()
        elif typ == "session.create":
            self._ensure_agent()
            self.sessions.create(str(cmd.get("name", "")) or "新会话")
            self.agent = self.sessions.current_agent()
            self._sync_permission_for_session(self.agent)   # 新会话固化自己的初始档位
            await self._push_snapshot()
            await self._push_permission_state()
        elif typ == "model.select":
            await self._select_model(str(cmd.get("model_id", "")))
        elif typ == "session.switch":
            self._ensure_agent()
            self.sessions.switch(str(cmd.get("session_id", "")))
            self.agent = self.sessions.current_agent()
            # 档位按会话独立：切换到目标会话时应用它自己的档位
            try:
                self._sync_permission_for_session(self.agent)
            except Exception as exc:  # noqa: BLE001
                _log(f"permission sync on switch failed: {exc}")
            await self._push_snapshot()
            await self._push_permission_state()
        elif typ == "session.rename":
            ok = self.sessions.rename(str(cmd.get("session_id", "")),
                                      str(cmd.get("name", "")))
            if not ok:
                await self.send(error("protocol", "会话名称不能为空"))
            await self._push_snapshot()
        elif typ == "session.delete":
            self._ensure_agent()
            previous = self._session_id()
            self.sessions.delete(str(cmd.get("session_id", "")))
            if self.sessions.current is None:
                self.sessions.create("新会话")
            if self._session_id() != previous:
                self.agent = self.sessions.current_agent()
                self._sync_permission_for_session()
            await self._push_snapshot()
            await self._push_permission_state()
        elif typ == "chat.state":
            self._ensure_agent()
            await self._push_chat_state()
        elif typ == "chat.history":
            self._ensure_agent()
            state = self._chat_state()
            state["history_target"] = str(cmd.get("target", ""))
            state["history"] = self._chat_history(str(cmd.get("target", "")))
            await self.send(state)
        elif typ == "chat.send":
            self._ensure_agent()
            target = str(cmd.get("target", ""))
            text = str(cmd.get("text", ""))
            if target and text:
                prev = self.chat_tasks.get(target)
                if prev is not None and not prev.done():
                    await self.send(chat_msg(
                        target=target, sender="system", name="系统",
                        content="上一条消息仍在投递，请稍候", own=False))
                else:
                    await self.send(chat_msg(
                        target=target, sender="user", name="我",
                        content=text, own=True))
                    self.chat_tasks[target] = asyncio.create_task(
                        self._chat_send(target, text))
        elif typ in ("chat.new_group", "chat.add_member", "chat.add_external"):
            self._ensure_agent()
            await self._handle_chat_admin(typ, cmd)
        elif typ == "archive.get":
            self._ensure_agent()
            await self.send(self._archive_state())
        elif typ == "permission.get":
            self._ensure_agent()
            await self._push_permission_state()
        elif typ == "permission.set":
            self._ensure_agent()
            level = str(cmd.get("level", "")).strip().lower()
            from yoai.bootstrap import PERMISSION_LEVELS, apply_permission_level
            from yoai.user_config import UserConfig
            if level not in PERMISSION_LEVELS:
                await self.send(error("protocol", f"未知权限档位: {level}"))
            else:
                policy = getattr(getattr(self.agent, "core", None), "policy", None)
                # SessionManager 的 agent_kwargs 里 policy 是所有会话共享的引用——
                # 必须先复制，否则改当前会话会污染模板、新会话继承旧档位。
                if policy is not None:
                    import copy as _copy
                    policy = _copy.copy(policy)
                    self.agent.core.policy = policy
                    executor = getattr(self.agent.core, "executor", None)
                    if executor is not None:
                        executor.policy = policy
                err = apply_permission_level(policy, level) if policy is not None else "agent 无策略对象"
                if err:
                    await self.send(error("protocol", err))
                else:
                    from yoai.user_config import UserConfig
                    cfg = UserConfig(_data_dir())
                    sid = self._session_id()
                    # 只改当前会话；全局默认不变（新会话仍沿用原默认）
                    cfg.set_permission(sid, level)
                    await self._push_permission_state()
        elif typ == "project.create":
            # 建项目（绑定宿主机文件夹）+ 在该项目内建一条项目模式会话。
            # 聊天模式会话不受影响；已有会话不自动归类。
            self._ensure_agent()
            from yoai.project import ProjectError
            try:
                proj = self.projects.create(
                    str(cmd.get("name", "")), str(cmd.get("path", "")))
            except ProjectError as exc:
                await self.send(error("project", str(exc)))
            else:
                sess = self.sessions.create(
                    str(cmd.get("session_name", "")) or f"{proj.name} · 会话",
                    mode="project", project_id=proj.id)
                self.agent = self.sessions.current_agent()
                self._sync_permission_for_session(self.agent)
                await self._push_snapshot()
                await self._push_permission_state()
        elif typ in ("project.list", "project.state"):
            self._ensure_agent()
            await self._push_snapshot()
        elif typ == "project.delete":
            self._ensure_agent()
            # 只删项目定义，不删项目内的会话（它们退回聊天模式语义，历史保留）。
            pid = str(cmd.get("project_id", ""))
            self.projects.delete(pid)
            for sess in self.sessions.list_sessions():
                if getattr(sess, "project_id", "") == pid:
                    sess.project_id = ""
                    sess.mode = "chat"
            self.sessions._save_index()
            self._agents_clear()
            self.agent = self.sessions.current_agent() if self.sessions.current() else None
            await self._push_snapshot()
        elif typ == "session.new_in_project":
            # 在项目内新建会话（项目模式下复用项目工具，记忆按项目隔离）
            self._ensure_agent()
            pid = str(cmd.get("project_id", ""))
            if self.projects.get(pid) is None:
                await self.send(error("project", f"项目不存在：{pid}"))
            else:
                sess = self.sessions.create(
                    str(cmd.get("name", "")) or "新会话", mode="project", project_id=pid)
                self.agent = self.sessions.current_agent()
                self._sync_permission_for_session(self.agent)
                await self._push_snapshot()
                await self._push_permission_state()
        elif typ == "browser.open":
            # 内嵌 iframe 被站点 X-Frame-Options 拒绝时的兜底：只放 http/https，
            # 复用标准库 webbrowser，不给 shell 能力、不回显 key。
            from urllib.parse import urlparse
            url = str(cmd.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                await self.send(error("browser", "只支持 http/https 网址"))
            else:
                import webbrowser
                try:
                    webbrowser.open(url)
                    await self.send(browser_opened(url=url))
                except Exception as exc:  # noqa: BLE001
                    await self.send(error("browser", f"打开系统浏览器失败：{type(exc).__name__}: {exc}"))
        elif typ in ("fs.list", "fs.read"):
            # 右侧「查看文件」面板：只读，路径限制在当前项目根 / 工作区内。
            from yoai.project import ProjectError, resolve_in_project
            root, label = self._file_root()
            rel = str(cmd.get("path", ""))
            try:
                target = resolve_in_project(root, rel)
                if typ == "fs.list":
                    if not target.is_dir():
                        raise ProjectError(f"不是目录：{rel}")
                    children = sorted(target.iterdir(),
                                      key=lambda p: (not p.is_dir(), p.name.lower()))
                    entries = [
                        {"name": c.name,
                         "path": c.relative_to(root).as_posix(),
                         "is_dir": c.is_dir()}
                        for c in children[:500]
                    ]
                    await self.send(file_tree(root=str(root), label=label,
                                              path=rel, entries=entries))
                else:
                    if not target.is_file():
                        raise ProjectError(f"不是文件：{rel}")
                    limit = 200_000
                    with target.open("rb") as handle:
                        raw = handle.read(limit + 1)
                    truncated = len(raw) > limit
                    await self.send(file_content(
                        root=str(root), path=rel,
                        content=raw[:limit].decode("utf-8", errors="replace"),
                        size=target.stat().st_size, truncated=truncated))
            except (ProjectError, OSError) as exc:
                await self.send(error("file", str(exc)))
        elif typ in ("attachment.prepare", "attachment.remove"):
            # 附件只登记到本地附件目录，不自动执行、不外传；文本类抽取进任务上下文。
            import shutil
            import uuid
            sid = self._session_id() or "shared"
            base = (self.attachments or _data_dir() / "attachments") / sid
            base.mkdir(parents=True, exist_ok=True)
            if typ == "attachment.remove":
                rid = str(cmd.get("id", ""))
                for candidate in base.glob(f"{rid}_*"):
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
                await self._push_snapshot()
                return True
            raw_path = str(cmd.get("path", "")).strip()
            if raw_path.lower().startswith("file://") or not raw_path:
                await self.send(error("file", "附件只接受本地文件路径"))
                return True
            source = Path(raw_path).expanduser()
            try:
                if not source.is_file():
                    raise ValueError("附件路径不是文件")
                size = source.stat().st_size
                if size > 10 * 1024 * 1024:
                    raise ValueError("附件超过 10MB 上限")
                rid = uuid.uuid4().hex[:10]
                target = base / f"{rid}_{source.name}"
                shutil.copyfile(source, target)
                text_ext = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".json", ".csv",
                            ".html", ".css", ".yml", ".yaml", ".toml", ".log"}
                text = ""
                truncated = False
                if source.suffix.lower() in text_ext:
                    with target.open("rb") as handle:
                        raw = handle.read(200_001)
                    truncated = len(raw) > 200_000
                    text = raw[:200_000].decode("utf-8", errors="replace")
                await self.send(attachment_ready(item={
                    "id": rid, "name": source.name, "size": size,
                    "path": str(target), "content": text, "truncated": truncated,
                }))
            except (OSError, ValueError) as exc:
                await self.send(error("file", f"附件登记失败：{exc}"))
        elif typ in ("message.retract", "message.edit", "task.regenerate"):
            # 软删除 + 分支：隐藏 Core 历史的一段区间，原始记录仍留 SQLite 可审计。
            from yoai.conversation_actions import content_hash
            sid = self._session_id()
            memory = getattr(getattr(self.agent, "core", None), "memory", None)
            if self.actions is None or memory is None:
                await self.send(error("message", "消息动作尚未初始化"))
                return True
            full = (memory.history_full() if hasattr(memory, "history_full")
                    else list(memory.history()))
            index = int(cmd.get("index", -1))
            if index < 0:
                # 新任务还没进历史时用 -1：按内容找最后一条匹配消息。
                needle = str(cmd.get("input", "")).strip()
                roles = ("assistant",) if typ == "task.regenerate" else ("user",)
                matches = [i for i, m in enumerate(full)
                           if getattr(m, "role", "") in roles
                           and (not needle or needle == str(getattr(m, "content", "")))]
                index = matches[-1] if matches else -1
            if index < 0 or index >= len(full):
                await self.send(error("message", "消息序号无效"))
                return True
            text = str(cmd.get("input", "") or getattr(full[index], "content", ""))
            if typ == "message.retract":
                end = index + 1
                for j in range(index + 1, len(full)):
                    if getattr(full[j], "role", "") == "user":
                        break
                    end = j + 1
                self.actions.add(session_id=sid, kind="retract", hide_from=index,
                                 hide_until=end, text_hash=content_hash(text))
                await self._push_snapshot()
                await self.send(message_updated(kind="retract", index=index))
                return True
            task_id = str(cmd.get("task_id", "")) or f"t{index}"
            run_id = str(cmd.get("run_id", "")) or f"r{index}"
            if typ == "message.edit":
                if not str(cmd.get("input", "")).strip():
                    await self.send(error("message", "编辑后的内容不能为空"))
                    return True
                self.actions.add(session_id=sid, kind="edit", hide_from=index,
                                 hide_until=len(full),
                                 text_hash=content_hash(str(cmd.get("input", ""))))
            else:
                self.actions.add(session_id=sid, kind="regenerate", hide_from=index,
                                 hide_until=len(full), text_hash=content_hash(text))
            await self._push_snapshot()
            await self.send(message_updated(
                kind="edit" if typ == "message.edit" else "regenerate", index=index))
            await self.start_task(task_id, run_id, text)
        elif typ == "share.export":
            path = Path(str(cmd.get("path", "")).strip()).expanduser()
            content = str(cmd.get("content", ""))
            count = int(cmd.get("count", 1))
            if path.suffix.lower() not in (".md", ".html"):
                await self.send(error("share", "只能导出 .md 或 .html"))
                return True
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                await self.send(share_exported(path=str(path), count=count))
            except OSError as exc:
                await self.send(error("share", f"导出失败：{exc}"))
        elif typ == "rsi.trial_start":
            try:
                controller = self._trial_controller()
                record = controller.start(
                    str(cmd.get("node_id", "")), str(cmd.get("scope", "")),
                    int(cmd.get("max_n", 20)))
                if self.router is not None and record.scope.startswith("tag:"):
                    self.router.set_trial(record.node_id, record.scope)
                await self.send(trial_state(record=record.to_dict()))
                await self.send(self._archive_state())
            except (ValueError, RuntimeError) as exc:
                await self.send(error("message", str(exc)))
        elif typ == "rsi.trial_stop":
            try:
                controller = self._trial_controller()
                record = controller.stop(str(cmd.get("trial_id", "")),
                                         str(cmd.get("reason", "")))
                if record and self.router and self.router.trial_node_id == record.node_id:
                    self.router.clear_trial()
                await self.send(trial_state(record=record.to_dict() if record else {}))
                await self.send(self._archive_state())
            except (ValueError, RuntimeError) as exc:
                await self.send(error("message", str(exc)))
        elif typ == "rsi.trial_report":
            try:
                report = self._trial_controller().report(str(cmd.get("trial_id", "")))
                await self.send(trial_report(report=report.to_dict()))
            except (ValueError, RuntimeError) as exc:
                await self.send(error("message", str(exc)))
        elif typ in ("rsi.promote_active", "rsi.reject"):
            try:
                controller = self._trial_controller()
                trial_id = str(cmd.get("trial_id", ""))
                record = controller.trials.get(trial_id)
                if typ == "rsi.promote_active":
                    report = controller.approve(
                        trial_id, str(cmd.get("approved_by", "")),
                        str(cmd.get("reason", "")))
                    to_state, verdict = "active", "approved"
                    reason = report.reason
                else:
                    updated = controller.reject(trial_id, str(cmd.get("reason", "")))
                    to_state, verdict = "retired", "rejected"
                    reason = str(cmd.get("reason", "")) or "试用被拒绝"
                if record and self.router and self.router.trial_node_id == record.node_id:
                    self.router.clear_trial()
                decision = {"node_id": record.node_id if record else "",
                            "from_state": "probation", "to_state": to_state,
                            "changed": True, "reason": reason, "verdict": verdict}
                await self.send(approval_recorded(decision=decision))
                await self.send(rsi_promoted(decision=decision))
                await self.send(self._archive_state())
            except (ValueError, RuntimeError) as exc:
                await self.send(error("message", str(exc)))
        elif typ == "rsi.rollback":
            try:
                from yoai.evolution import EvolutionArchive, RollbackMonitor
                if self.evidence_store is None or self.feedback_store is None \
                        or self.evolution_reports is None:
                    raise RuntimeError("RSI 回滚存储尚未初始化")
                archive = EvolutionArchive(_data_dir() / "evolution" / "evolution.json")
                decision = RollbackMonitor(archive, self.evidence_store,
                                           self.feedback_store,
                                           self.evolution_reports).check(
                    str(cmd.get("node_id", "")))
                await self.send(rsi_rolled_back(decision=decision.to_dict()))
                await self.send(self._archive_state())
            except (ValueError, RuntimeError) as exc:
                await self.send(error("message", str(exc)))
        elif typ == "rsi.validate":
            # R2.2 验证 + R3.1 受控晋升：improved→probation，regression→retired；
            # 绝不直接 active。
            from yoai.evolution import CandidateValidator, EvolutionArchive, R3Promoter
            if self.evidence_store is None or self.evolution_reports is None:
                await self.send(error("message", "RSI 验证存储尚未初始化"))
                return True
            archive = EvolutionArchive(_data_dir() / "evolution" / "evolution.json")
            validator = CandidateValidator(archive, self.evidence_store, self.evolution_reports)
            validation = validator.validate(str(cmd.get("node_id", "")))
            await self.send(rsi_validated(validation=validation.to_dict()))
            promoter = R3Promoter(archive, self.evidence_store, self.evolution_reports)
            decision = promoter.apply(validation)
            await self.send(rsi_promoted(decision=decision.to_dict()))
            await self.send(self._archive_state())
        elif typ == "rsi.trigger":
            # R2.1：shadow 触发，只生成 candidate 节点，不进路由、不晋升。
            from yoai.evidence import build_boundary_report
            from yoai.evolution import EvolutionArchive, TriggerEngine
            if (self.evidence_store is None or self.feedback_store is None
                    or self.evolution_reports is None):
                await self.send(error("message", "RSI 存储尚未初始化"))
                return True
            tags = [str(t) for t in (cmd.get("tags") or []) if str(t).strip()]
            archive = EvolutionArchive(_data_dir() / "evolution" / "evolution.json")
            report = build_boundary_report(self.evidence_store, self.feedback_store)
            engine = TriggerEngine(archive, self.evidence_store, self.evolution_reports)
            decisions = [d.to_dict() for d in engine.evaluate(report, tags=tags)]
            await self.send(rsi_triggered(decisions=decisions))
            await self.send(self._archive_state())
            await self._push_boundary_state()
        elif typ == "boundary.get":
            await self._push_boundary_state()
        elif typ == "feedback.record":
            # RSI R0：只采集用户动作，不做任何触发/晋升判断。
            import uuid
            from yoai.evidence import FeedbackSignal
            from yoai.evolution.fingerprint import fingerprint
            kind = str(cmd.get("kind", "")).strip()
            polarity = -1 if kind in ("retract", "edit", "regenerate") else (
                1 if kind in ("copy", "share") else 0)
            task = str(cmd.get("task", ""))
            run_id = str(cmd.get("run_id", ""))
            evidence = None
            if self.evidence_store is not None:
                evidence_id = self.run_evidence.get(run_id) or str(cmd.get("evidence_id", ""))
                if evidence_id:
                    evidence = self.evidence_store.get(evidence_id)
                if evidence is None and task:
                    matches = [e for e in self.evidence_store.query()
                               if e.task == task or task in e.task]
                    evidence = matches[-1] if matches else None
            fp = fingerprint(task) if task else None
            signal = FeedbackSignal(
                id=uuid.uuid4().hex[:12],
                evidence_id=evidence.id if evidence else str(cmd.get("evidence_id", "")),
                run_id=run_id, session_id=str(cmd.get("session_id", "") or self._session_id()),
                kind=kind, polarity=polarity,
                task_fingerprint=evidence.task_fingerprint if evidence else (fp.key if fp else ""),
                fingerprint_tags=evidence.fingerprint_tags if evidence else (fp.tags if fp else ()),
                note=str(cmd.get("note", ""))[:500],
            )
            if self.feedback_store is not None:
                self.feedback_store.add(signal)
            await self.send(feedback_recorded(signal=signal.to_dict()))
            await self._push_boundary_state()
        elif typ == "shutdown":
            for task in list(self.tasks.values()):
                task.cancel()
            for fut in self.pending_approvals.values():
                if not fut.done():
                    fut.cancel()
            if self.mcp_manager is not None:
                self.mcp_manager.close()
            return False
        else:
            await self.send(error("protocol", f"unknown command: {typ}",
                                  task_id=task_id, run_id=run_id))
        return True

    async def _handle_chat_admin(self, typ: str, cmd: dict[str, Any]) -> None:
        """建群 / 拉人 / 外部智能体加入群（旧端 ChatPanel 语义）。"""
        target = str(cmd.get("target", ""))
        try:
            if typ == "chat.new_group":
                name = str(cmd.get("name", "")).strip()
                if name:
                    peer_ids = list(self.channel.peers.keys())
                    self.channel.create_group(name, peer_ids)
            elif typ == "chat.add_member":
                peer_id = str(cmd.get("peer_id", ""))
                group = next(
                    (g for g in self.channel.groups() if g.id == target), None)
                if group and peer_id:
                    self.channel.add_member(group.id, peer_id)
            elif typ == "chat.add_external":
                name = str(cmd.get("name", ""))
                peer_id = self._register_external(name)
                group = next(
                    (g for g in self.channel.groups() if g.id == target), None)
                if group and peer_id:
                    self.channel.add_member(group.id, peer_id)
        except Exception as exc:  # noqa: BLE001
            await self.send(chat_msg(
                target=target, sender="system", name="系统",
                content=f"{type(exc).__name__}: {exc}", own=False))
        await self._push_chat_state()


def _stdin_commands(rt: Runtime, queue: asyncio.Queue) -> None:
    """专用线程阻塞读 stdin（daemon=True：shutdown 后进程可立即退出，
    不会像 run_in_executor 的默认线程那样在 readline 上卡住解释器退出）。"""
    import threading
    loop = asyncio.get_running_loop()

    def _read() -> None:
        while True:
            line = sys.stdin.readline()
            if not line:      # EOF = 宿主关闭
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "__eof__"})
                return
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    loop.call_soon_threadsafe(queue.put_nowait, obj)
                else:
                    asyncio.run_coroutine_threadsafe(
                        rt.send(error("protocol", "command must be an object")), loop)
            except json.JSONDecodeError as exc:
                asyncio.run_coroutine_threadsafe(
                    rt.send(error("protocol", f"bad json: {exc}")), loop)

    t = threading.Thread(target=_read, name="stdin-reader", daemon=True)
    t.start()


async def amain() -> None:
    rt = Runtime()
    queue: asyncio.Queue = asyncio.Queue()
    _stdin_commands(rt, queue)   # 启动 daemon 读线程（非协程，不需要 create_task）
    try:
        while True:
            cmd = await queue.get()
            if cmd.get("type") == "__eof__":
                break
            if not await rt.handle(cmd):
                break
    finally:
        for task in list(rt.tasks.values()):
            task.cancel()
        if rt.tasks:
            await asyncio.gather(*rt.tasks.values(), return_exceptions=True)


def main() -> int:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        import traceback
        _log(f"fatal: {type(exc).__name__}: {exc}")
        _log(traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
