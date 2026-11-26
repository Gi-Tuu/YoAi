"""执行证据采集器 · 从真实 Core 事件流采证据，不伪造。

用法：
    collector = ExecutionEvidenceCollector(store, meta)
    async for event in agent.astream(task):
        collector.observe(event)
    # DiagnosticEvent 走 Core 的 on_diagnostic 回调（构造时注入）
    evidence = collector.finish(task, fingerprint, ...)

采集内容全部来自 Core 事件：
- DONE: strategy / status / model_calls / standard_calls / strong_calls / verification / budget
- ERROR: stage / error（工具/网关问题信号）
- TOOL_CALL: 工具名序列
- DiagnosticEvent: kind / level / message（模型超时/降级/发现失败等诊断）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from yai_core.types import AgentEvent, EventType

from yoai.evidence.models import ExecutionEvidence


@dataclass
class _Accumulator:
    strategy: str = ""
    status: str = ""
    model_calls: int = 0
    standard_calls: int = 0
    strong_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    final_text: str = ""


class ExecutionEvidenceCollector:
    """一次执行的事件采集器（非线程安全，一次 run 一个实例）。"""

    def __init__(self) -> None:
        self._acc = _Accumulator()

    def observe(self, event: AgentEvent) -> None:
        """观察一条 Core 事件（同步、旁路，不影响主流程）。"""
        data = event.data or {}
        et = event.type
        if et == EventType.DONE:
            self._acc.strategy = str(data.get("strategy", ""))
            self._acc.status = str(data.get("status", "ok"))
            self._acc.model_calls = int(data.get("model_calls", 0) or 0)
            self._acc.standard_calls = int(data.get("standard_calls", 0) or 0)
            self._acc.strong_calls = int(data.get("strong_calls", 0) or 0)
            self._acc.final_text = str(data.get("final_text", "") or "")
            if data.get("verification"):
                self._acc.verification = data["verification"]
            # usage 来源优先级：显式 usage > budget 快照
            if isinstance(data.get("usage"), dict):
                self._acc.usage = self._parse_usage(data["usage"])
            elif isinstance(data.get("budget"), dict):
                self._acc.usage = self._parse_usage(data["budget"])
        elif et == EventType.ERROR:
            self._acc.errors.append({
                "stage": str(data.get("stage", "")),
                "error": str(data.get("error", ""))[:300],
            })
        elif et == EventType.TOOL_CALL:
            tool = data.get("tool", "")
            if tool:
                self._acc.tool_calls.append(str(tool))
        elif et == EventType.STRATEGY_SELECTED:
            if not self._acc.strategy:
                self._acc.strategy = str(data.get("strategy", ""))

    def observe_diagnostic(self, diagnostic: Any) -> None:
        """观察一条 DiagnosticEvent（Core on_diagnostic 回调）。"""
        self._acc.diagnostics.append({
            "kind": str(getattr(diagnostic, "kind", "")),
            "level": str(getattr(diagnostic, "level", "")),
            "message": str(getattr(diagnostic, "message", ""))[:300],
            "data": dict(getattr(diagnostic, "data", {}) or {}),
        })

    @staticmethod
    def _parse_usage(raw: dict[str, Any]) -> dict[str, int]:
        out: dict[str, int] = {}
        for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                  "model_calls", "tool_calls", "tokens"):
            v = raw.get(k)
            if isinstance(v, (int, float)):
                out[k] = int(v)
        return out

    def finish(
        self,
        *,
        session_id: str,
        task: str,
        task_fingerprint: str,
        fingerprint_tags: tuple[str, ...],
        sample_class: str,
        expert_id: str | None,
        parent_id: str | None,
        usage_override: dict[str, int] | None = None,
        route_decision: dict[str, Any] | None = None,
        trial_id: str = "",
        trial_role: str = "",
    ) -> ExecutionEvidence:
        """收尾产出不可变证据（事件流快照）。

        usage 优先取事件流（Core 配置 Budget 时 DONE 会带）；
        宿主可传 usage_override（如 GatewayModelProvider.total_usage）补充真实用量。
        """
        a = self._acc
        usage = dict(a.usage) if a.usage else dict(usage_override or {})
        return ExecutionEvidence.create(
            session_id=session_id,
            task=task,
            task_fingerprint=task_fingerprint,
            fingerprint_tags=fingerprint_tags,
            sample_class=sample_class,
            expert_id=expert_id,
            parent_id=parent_id,
            strategy=a.strategy or "unknown",
            status=a.status or "unknown",
            model_calls=a.model_calls,
            standard_calls=a.standard_calls,
            strong_calls=a.strong_calls,
            usage=usage,
            errors=a.errors,
            diagnostics=a.diagnostics,
            tool_calls=a.tool_calls,
            verification=a.verification,
            route_decision=route_decision,
            trial_id=trial_id, trial_role=trial_role,
            final_text_preview=a.final_text,
        )
