"""S2：把调度器接进桌面 runtime 的桥（不依赖 Tauri / Qt / Core 顶层导入，可单测）。

runtime 只需：
1. 构造 ``SchedulerHost(data_dir, sessions, send, ...)``；
2. 给专用会话的 agent 注入 ``agent_overrides()``（独立 channel + 无人值守 policy）；
3. hello 后 ``await start()``，shutdown 时 ``await shutdown()``；
4. ``schedule.*`` 命令交给 ``handle()``。

安全要点（方案第 6 节）：
- 定时任务只在专用「⏰ 定时任务」会话里跑，**每次运行前重新锁定** policy 为
  无人值守白名单（防止用户切到该会话改过档位后被继承）；
- 审批请求走本模块自己的 channel：运行中一律按白名单当场决定、不弹窗、记账；
  不在运行中（用户在这个会话里手动聊天）才转给正常的弹窗回调；
- 澄清请求在无人值守时直接回一句"按最合理假设继续"，不会卡住。

对齐 OpenClaw：每次运行的提示前缀 ``[定时任务 · 名称]``，便于在会话历史里追溯；
首次启动预置一个默认关闭的「主动检查」任务，删掉后不再自动出现。
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from yoai.scheduler.engine import SchedulerEngine
from yoai.scheduler.memory_window import RunWindowMemory
from yoai.scheduler.models import (
    SCHEDULER_SESSION_NAME,
    Job,
    RunRecord,
    RunResult,
    SchedulerError,
)
from yoai.scheduler.policy import UnattendedGate, allowed_set
from yoai.scheduler.presets import HEARTBEAT_ID, heartbeat_job
from yoai.scheduler.store import SchedulerStore
from yoai.scheduler.triggers import describe

PROTOCOL_VERSION = 1
CLARIFY_UNATTENDED = (
    "（无人值守运行：没有人能回答澄清问题。请按最合理的假设继续，"
    "并在结果里说明你做了哪些假设。）"
)
EDITABLE_FIELDS = (
    "name", "trigger", "prompt", "enabled", "allowed_tools", "misfire", "on_interrupt",
    "timeout_s", "active_hours", "idle_only", "scratch", "skip_if_scratch_empty",
)

RequestHost = Callable[[str, dict[str, Any]], Awaitable[Any]]


def _job_state(job: Job, *, running: bool = False, waiting: bool = False) -> dict[str, Any]:
    return {**job.to_dict(), "schedule_text": describe(job.trigger),
            "running": running, "waiting": waiting}


def disabled_message(data_dir: str | Path, typ: str, cmd: dict[str, Any]) -> dict[str, Any]:
    """调度器未开启时，只读回答 schedule.list / state / runs（S4 界面据此显示「未开启」）。

    目录不存在就返回空，不会为了"看一眼"去创建 output/scheduler/。
    """
    root = Path(data_dir) / "scheduler"
    store = SchedulerStore(root) if root.is_dir() else None
    if typ == "schedule.runs":
        job_id = str(cmd.get("job_id", "") or "")
        limit = int(cmd.get("limit", 20) or 20)
        runs = store.runs(job_id, limit=limit) if store is not None else []
        return {"v": PROTOCOL_VERSION, "type": "schedule.runs", "job_id": job_id,
                "runs": [r.to_dict() for r in runs]}
    jobs = [_job_state(j) for j in store.list_jobs()] if store is not None else []
    return {"v": PROTOCOL_VERSION, "type": "schedule.state", "enabled": False, "jobs": jobs,
            "session_id": "", "session_name": SCHEDULER_SESSION_NAME}


def _default_policy(allowed: set[str]) -> Any:
    from yai_core.policy import AllowlistPolicy
    return AllowlistPolicy(mode="auto", allowed=allowed)


def _default_clean(text: str) -> str:
    try:
        from yoai.bootstrap import clean_final_text
        return clean_final_text(text)
    except Exception:  # noqa: BLE001
        return text


def _event_name(ev: Any) -> str:
    typ = getattr(ev, "type", "")
    return str(getattr(typ, "value", typ))


class SchedulerHost:
    def __init__(
        self,
        data_dir: str | Path,
        sessions: Any,
        send: Callable[[dict[str, Any]], Awaitable[Any]],
        *,
        is_busy: Callable[[], bool],
        channel_factory: Callable[[RequestHost], Any],
        fallback_request: RequestHost | None = None,
        policy_factory: Callable[[set[str]], Any] | None = None,
        clean_text: Callable[[str], str] | None = None,
        on_history_changed: Callable[[], Any] | None = None,
        goals_provider: Callable[[], list[dict[str, Any]]] | None = None,
        log: Callable[[str], None] | None = None,
        clock: Callable[[], Any] | None = None,
        tick_s: float = 30,
        provision: bool = True,
        evidence_store: Any = None,          # S5-4：EvidenceStore，或返回它的 callable
        collector_factory: Callable[[], Any] | None = None,
        fresh_context: bool | None = None,   # S5-3：None = 读 YOAI_SCHEDULER_FRESH（默认开）
    ) -> None:
        self.root = Path(data_dir) / "scheduler"
        self.store = SchedulerStore(self.root)
        self.sessions = sessions
        self._send = send
        self._fallback = fallback_request
        self._policy_factory = policy_factory or _default_policy
        self._clean = clean_text or _default_clean
        self._on_history = on_history_changed
        self._log = log or logging.getLogger("yoai.scheduler").info
        self._gate: UnattendedGate | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._evidence_store = evidence_store
        self._collector_factory = collector_factory
        if fresh_context is None:
            fresh_context = os.environ.get("YOAI_SCHEDULER_FRESH", "1").strip() != "0"
        self.fresh_context = bool(fresh_context)
        self._remove_goal_listener: Callable[[], None] | None = None
        self.channel = channel_factory(self._request_host)
        self.engine = SchedulerEngine(
            self.store, self._run_job, clock=clock, is_busy=is_busy,
            goals_provider=goals_provider or self._goals, notify=self._notify, tick_s=tick_s,
        )
        self.session_id = self._ensure_session()
        self.started = False
        if provision:
            self._provision_presets()

    # ================= 会话 =================
    @property
    def _meta_path(self) -> Path:
        return self.root / "meta.json"

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_session(self) -> str:
        """找到或创建专用会话；**不改变用户当前所在的会话**。"""
        meta = self._read_json(self._meta_path)
        sid = str(meta.get("session_id", ""))
        if sid and self.sessions.get(sid) is not None:
            return sid
        for s in self.sessions.list_sessions():
            if getattr(s, "name", "") == SCHEDULER_SESSION_NAME:
                sid = s.id
                break
        else:
            current = getattr(self.sessions, "current", None)
            previous = getattr(current, "id", None)
            sid = self.sessions.create(SCHEDULER_SESSION_NAME).id
            if previous:
                self.sessions.switch(previous)
        meta["session_id"] = sid
        self._write_json(self._meta_path, meta)
        return sid

    def owns(self, agent: Any) -> bool:
        agents = getattr(self.sessions, "_agents", {}) or {}
        return agent is not None and agents.get(self.session_id) is agent

    def is_session(self, session_id: str) -> bool:
        return bool(session_id) and session_id == self.session_id

    def agent_overrides(self) -> dict[str, Any]:
        """SessionManager 给专用会话建 agent 时合并的参数。"""
        return {"channel": self.channel, "policy": self._policy_factory(allowed_set())}

    def busy(self) -> bool:
        return self.engine.any_running()

    def wrap_memory(self, session_id: str, memory: Any) -> Any:
        """S5-3：给专用会话的 memory 套上运行窗口（runtime 在建该会话的 agent 时调用）。"""
        if self.fresh_context and self.is_session(session_id) and not isinstance(memory, RunWindowMemory):
            return RunWindowMemory(memory)
        return memory

    def tool_specs(self) -> list[Any]:
        """S3：给每个会话的 agent 注册 schedule_* 工具。"""
        from yoai.scheduler.tools import schedule_tool_specs
        return schedule_tool_specs(self)

    def notify_changed(self) -> None:
        """对话工具改了任务后推一次 schedule.state（可在任意线程调用）。"""
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def _schedule() -> None:
            asyncio.ensure_future(self.push_state())
        try:
            loop.call_soon_threadsafe(_schedule)
        except RuntimeError:
            pass

    def _goals(self) -> list[dict[str, Any]]:
        agent = self.sessions.agent_for(self.session_id)
        goals = getattr(agent, "goals", None)
        return list(goals.list_goals()) if goals is not None else []

    def _provision_presets(self) -> None:
        """只预置一次（OpenClaw 语义：删掉默认任务是持久的选择）。"""
        path = self.root / "provisioned.json"
        receipt = self._read_json(path)
        done = set(receipt.get("presets", []))
        if HEARTBEAT_ID in done:
            return
        try:
            if self.store.get(HEARTBEAT_ID) is None:
                self.engine.add_job(heartbeat_job())
            done.add(HEARTBEAT_ID)
            self._write_json(path, {"presets": sorted(done)})
        except Exception as exc:  # noqa: BLE001 - 预置失败不影响启动
            self._log(f"scheduler preset failed: {exc}")

    # ================= 权限 =================
    def _lock_policy(self, agent: Any, extra: list[str]) -> None:
        core = getattr(agent, "core", None)
        policy = getattr(core, "policy", None)
        if core is None or policy is None:
            raise RuntimeError("定时任务会话缺少权限策略对象，为安全起见拒绝运行")
        locked = copy.copy(policy)
        locked.mode = "auto"
        locked.allowed = allowed_set(extra)
        core.policy = locked
        executor = getattr(core, "executor", None)
        if executor is not None:
            executor.policy = locked

    async def _request_host(self, kind: str, payload: dict[str, Any]) -> Any:
        gate = self._gate
        if gate is None:                       # 不在定时运行中：用户在这个会话手动聊天
            if self._fallback is not None:
                return await self._fallback(kind, payload)
            return False if kind == "approval/request" else ""
        if kind == "approval/request":
            tool = str(payload.get("tool", "") or payload.get("name", ""))
            return gate.decide(tool)
        return CLARIFY_UNATTENDED

    # ================= 执行 =================
    async def _run_job(self, job: Job, record: RunRecord, prompt: str) -> RunResult:
        if self.sessions.get(self.session_id) is None:   # 用户删了专用会话 → 重建
            self.session_id = self._ensure_session()
        agent = self.sessions.agent_for(self.session_id)
        extra = list(job.allowed_tools) if job is not None else []
        self._lock_policy(agent, extra)
        gate = UnattendedGate(extra=extra)
        self._gate = gate
        name = job.name if job is not None else record.job_name
        task_text = f"[定时任务 · {name}]\n{prompt}"
        final_text, stream, status, errors = "", "", None, []
        memory = getattr(getattr(agent, "core", None), "memory", None)
        window = memory if isinstance(memory, RunWindowMemory) else None
        if window is not None:
            window.begin()                     # 本次运行看不到之前运行的对话
        collector = self._make_collector()
        try:
            async for ev in agent.astream(task_text):
                if collector is not None:
                    try:
                        collector.observe(ev)
                    except Exception:  # noqa: BLE001 - 证据是旁路，坏了就不采
                        collector = None
                ev_name = _event_name(ev)
                data = dict(getattr(ev, "data", {}) or {})
                if ev_name == "delta":
                    stream += str(data.get("text", ""))
                elif ev_name == "permission_denied":
                    tool = str(data.get("tool", ""))
                    if tool and tool not in gate.denied:
                        gate.denied.append(tool)
                elif ev_name == "error":
                    errors.append(str(data.get("message") or data.get("error") or data)[:300])
                elif ev_name == "done":
                    final_text = str(data.get("final_text", "") or "")
                    status = str(data.get("status", "ok"))
        finally:
            self._gate = None
            if window is not None:
                window.end()
            try:
                self.sessions.touch(self.session_id, delta=2)
            except Exception:  # noqa: BLE001
                pass
        evidence_id = self._record_evidence(collector, agent, task_text, prompt) if collector else ""

        text = self._clean(final_text if final_text.strip() else stream).strip()
        ok = status == "ok" and bool(text)
        if not text:
            text = "；".join(errors) if errors else "（没有输出）"
        elif status not in (None, "ok") and errors:
            text = f"{text}\n（错误：{'；'.join(errors)}）"
        if status is None and not errors:
            text = f"{text}（未收到完成事件）"
        return RunResult(ok=ok, summary=text, denied_tools=list(gate.denied), evidence_id=evidence_id)

    # ================= 证据（S5-4） =================
    def _store(self) -> Any:
        store = self._evidence_store
        return store() if callable(store) else store

    def _make_collector(self) -> Any:
        if self._store() is None:
            return None
        try:
            if self._collector_factory is not None:
                return self._collector_factory()
            from yoai.evidence import ExecutionEvidenceCollector
            return ExecutionEvidenceCollector()
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduler evidence collector failed: {exc}")
            return None

    @staticmethod
    def _fingerprint(prompt: str) -> tuple[str, tuple[str, ...]]:
        from yoai.evolution.fingerprint import fingerprint
        fp = fingerprint(prompt)
        return fp.key, tuple(fp.tags)

    def _record_evidence(self, collector: Any, agent: Any, task_text: str, prompt: str) -> str:
        """与对话同一套证据：边界看板 / 归因 / RSI 都能用上定时运行的样本。失败只记日志。"""
        store = self._store()
        if store is None:
            return ""
        try:
            fp_key, fp_tags = self._fingerprint(prompt)   # 按任务内容算，不含「定时任务」前缀
            provider = getattr(agent, "model", None)
            decision = getattr(provider, "last_decision", None)
            evidence = collector.finish(
                session_id=self.session_id,
                task=task_text,
                task_fingerprint=fp_key,
                fingerprint_tags=fp_tags,
                sample_class="evolution",
                expert_id=getattr(provider, "last_expert_id", None),
                parent_id=getattr(provider, "last_parent_id", None),
                usage_override=getattr(provider, "total_usage", None),
                route_decision=decision.to_dict() if hasattr(decision, "to_dict") else None,
            )
            store.add(evidence)
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduler evidence record failed: {exc}")
            return ""
        try:
            from yoai.evidence import AttributionEngine
            store.add_attribution(AttributionEngine(store).attribute(evidence))
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduler attribution failed: {exc}")
        return str(getattr(evidence, "id", ""))

    # ================= 消息 =================
    async def _emit(self, msg: dict[str, Any]) -> None:
        try:
            await self._send({"v": PROTOCOL_VERSION, **msg})
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduler send failed: {exc}")

    async def _call_history(self) -> None:
        if self._on_history is None:
            return
        try:
            res = self._on_history()
            if inspect.isawaitable(res):
                await res
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduler history refresh failed: {exc}")

    async def _notify(self, kind: str, payload: dict[str, Any]) -> None:
        key = "job" if kind == "job_disabled" else "run"
        await self._emit({"type": f"schedule.{kind}", key: payload})
        if kind in ("run_finished", "run_interrupted", "job_disabled"):
            await self.push_state()
        if kind == "run_finished" and payload.get("state") != "skipped":
            await self._call_history()

    async def push_state(self) -> None:
        await self._emit({
            "type": "schedule.state",
            "enabled": True,
            "jobs": self.engine.state(),
            "session_id": self.session_id,
            "session_name": SCHEDULER_SESSION_NAME,
        })

    async def _ack(self, command: str, ok: bool, message: str = "") -> None:
        await self._emit({"type": "schedule.ack", "command": command, "ok": ok, "message": message})

    # ================= 生命周期 =================
    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._loop = asyncio.get_running_loop()
        from yoai.goals import add_goal_listener
        self._remove_goal_listener = add_goal_listener(self._on_goal_event)
        interrupted = await self.engine.startup()
        self.engine.start()
        if interrupted:
            self._log(f"scheduler: {len(interrupted)} 个运行上次被中断")
        await self.push_state()

    async def shutdown(self) -> None:
        if self._remove_goal_listener is not None:
            self._remove_goal_listener()
            self._remove_goal_listener = None
        await self.engine.shutdown()

    # ================= 目标事件（S5-1） =================
    def _on_goal_event(self, event: str, goal: dict[str, Any], manager: Any, **extra: Any) -> None:
        """GoalManager 的回调：可能在工作线程里被调用，所以只投递到事件循环。"""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        agents = getattr(self.sessions, "_agents", {}) or {}
        own = agents.get(self.session_id)
        if own is not None and getattr(own, "goals", None) is manager and self.engine.any_running():
            return   # 定时任务自己改的目标不再触发事件任务，防止自己触发自己
        payload = {
            "goal_id": str(goal.get("id", "")),
            "goal_title": str(goal.get("title", "")),
            "status": str(goal.get("status", "")),
            "old_status": str(extra.get("old_status", "")),
        }

        def _schedule() -> None:
            asyncio.ensure_future(self._emit_goal_event(event, payload))
        try:
            loop.call_soon_threadsafe(_schedule)
        except RuntimeError:
            pass

    async def _emit_goal_event(self, event: str, payload: dict[str, Any]) -> None:
        try:
            await self.engine.emit(event, **payload)
        except Exception as exc:  # noqa: BLE001
            self._log(f"scheduler goal event failed: {exc}")

    # ================= 命令 =================
    def _job_from_command(self, raw: Any) -> Job:
        if not isinstance(raw, dict):
            raise SchedulerError("缺少任务定义 job")
        job_id = str(raw.get("id", "") or "")
        existing = self.store.get(job_id) if job_id else None
        if existing is None:
            if job_id:
                raise SchedulerError(f"找不到任务 {job_id}（可能已被删除）")
            # 新建只接受可编辑字段：不能借新建写入运行统计 / 来源 / id
            fresh = {k: raw[k] for k in EDITABLE_FIELDS if k in raw}
            fresh.setdefault("name", "")
            fresh.setdefault("prompt", "")
            fresh.setdefault("trigger", {})
            return Job.from_dict(fresh)
        merged = existing.to_dict()
        for key in EDITABLE_FIELDS:
            if key in raw:
                merged[key] = raw[key]
        return Job.from_dict(merged)

    async def handle(self, typ: str, cmd: dict[str, Any]) -> None:
        job_id = str(cmd.get("job_id", "") or "")
        try:
            if typ in ("schedule.list", "schedule.state"):
                await self.push_state()
                return
            if typ == "schedule.runs":
                runs = self.store.runs(job_id, limit=int(cmd.get("limit", 20) or 20))
                await self._emit({"type": "schedule.runs", "job_id": job_id,
                                  "runs": [r.to_dict() for r in runs]})
                return
            if typ == "schedule.save":
                job = self._job_from_command(cmd.get("job"))
                if self.store.get(job.id) is None:
                    self.engine.add_job(job)
                    msg = f"已创建：{job.name}"
                else:
                    self.engine.update_job(job)
                    msg = f"已保存：{job.name}"
            elif typ == "schedule.delete":
                if not self.engine.remove_job(job_id):
                    raise SchedulerError(f"找不到任务 {job_id}")
                msg = "已删除"
            elif typ == "schedule.toggle":
                job = self.engine.set_enabled(job_id, bool(cmd.get("enabled", True)))
                msg = f"{'已开启' if job.enabled else '已关闭'}：{job.name}"
            elif typ == "schedule.run_now":
                run_id = await self.engine.run_now(job_id)
                msg = "已开始运行" if run_id else "前台有任务，结束后马上运行"
            elif typ == "schedule.cancel":
                if not self.engine.cancel_run(job_id):
                    raise SchedulerError("这个任务现在没有在运行")
                msg = "已取消"
            else:
                raise SchedulerError(f"未知命令：{typ}")
        except SchedulerError as exc:
            await self._ack(typ, False, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            await self._ack(typ, False, f"{type(exc).__name__}: {exc}")
            return
        await self._ack(typ, True, msg)
        await self.push_state()
