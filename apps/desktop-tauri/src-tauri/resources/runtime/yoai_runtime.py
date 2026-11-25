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
    PROTOCOL_VERSION, Seq, approval_request, archive_state, chat_msg,
    chat_state, encode, error, event, final, ready, snapshot, status,
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
        self.sessions: Any = None
        self.channel: Any = None          # peer 通讯（通讯页）
        self.registry: dict[str, Any] = {}  # 外部智能体注册表
        self.evidence_store: Any = None   # 证据落盘（旁路）
        self.tasks: dict[str, asyncio.Task] = {}       # run_id -> task
        self.chat_tasks: dict[str, asyncio.Task] = {}  # target -> 投递任务
        self.running: dict[str, tuple[str, str]] = {}  # run_id -> (task_id, cancelled?)
        self.pending_approvals: dict[str, asyncio.Future] = {}
        self.stream_text: dict[str, str] = {}  # run_id -> 累积流式文本（final 空时兜底）
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
        from yoai.bootstrap import agent_kwargs, build_main_model
        from yoai.session import SessionManager
        from yai_core_sidecar_channel import make_sidecar_channel  # 本目录辅助

        data_dir = _data_dir()
        channel_cb = make_sidecar_channel(self._request_host)
        provider, _archive = build_main_model(data_dir)
        self.sessions = SessionManager(
            data_dir / "sessions",
            model_factory=lambda: provider,
            agent_kwargs=agent_kwargs(data_dir, channel=channel_cb),
        )
        # 首次启动（数据目录为空）必须建初始会话——旧端 app.py main() 语义，
        # 否则 current_agent() 会 KeyError，新用户第一句话就失败。
        if not self.sessions.list_sessions():
            self.sessions.create("新会话")
        self.agent = self.sessions.current_agent()

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
        sessions = [s.to_dict() for s in self.sessions.list_sessions()]
        current = self.sessions.current
        history: list[dict[str, Any]] = []
        try:
            for message in self.agent.core.memory.history():
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
                history.append({"role": role, "text": str(content)})
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
        return snapshot(
            sessions=sessions,
            current_id=current.id if current else "",
            history=history,
            model=self._model_name(),
            facts=facts,
            goals=goals,
            write_stats=write_stats,
            tools=tools,
        )

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
                "created_at": str(getattr(node, "created_at", "")),
                "prompt_suffix": str(getattr(node.spec, "prompt_suffix", "") or ""),
            })
        return archive_state(nodes=nodes)

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

                async for ev in self.agent.astream(user_input):
                    name = getattr(ev.type, "value", str(ev.type))
                    data = dict(getattr(ev, "data", {}) or {})
                    seq = self.seq.for_run(task_id, run_id)
                    if collector is not None:
                        collector.observe(ev)
                    if name == "delta":
                        self.stream_text[run_id] = (
                            self.stream_text.get(run_id, "") + str(data.get("text", "")))
                    if name == "done":
                        text = str(data.get("final_text", ""))
                        if not text.strip():
                            # final 空但流式有内容（异常收尾/网关差异）→ 流式兜底
                            text = self.stream_text.get(run_id, "")
                        try:
                            from yoai.bootstrap import clean_final_text
                            text = clean_final_text(text)
                        except Exception:  # noqa: BLE001
                            pass
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
                    )
                    self.evidence_store.add(evidence)
                    attribution = AttributionEngine(self.evidence_store).attribute(evidence)
                    self.evidence_store.add_attribution(attribution)
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
            await self._push_snapshot()
        elif typ == "session.switch":
            self._ensure_agent()
            self.sessions.switch(str(cmd.get("session_id", "")))
            self.agent = self.sessions.current_agent()
            await self._push_snapshot()
        elif typ == "session.rename":
            ok = self.sessions.rename(str(cmd.get("session_id", "")),
                                      str(cmd.get("name", "")))
            if not ok:
                await self.send(error("protocol", "会话名称不能为空"))
            await self._push_snapshot()
        elif typ == "session.delete":
            self._ensure_agent()
            self.sessions.delete(str(cmd.get("session_id", "")))
            self.agent = self.sessions.current_agent()
            await self._push_snapshot()
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
        elif typ == "shutdown":
            for task in list(self.tasks.values()):
                task.cancel()
            for fut in self.pending_approvals.values():
                if not fut.done():
                    fut.cancel()
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
