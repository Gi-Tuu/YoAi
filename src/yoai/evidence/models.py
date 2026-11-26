"""证据基础设施的数据契约 · M2 前置。

核心诚实原则：证据只来自真实执行事件流（DONE/ERROR/DiagnosticEvent/usage），
不从模型自评或想象生成。每条证据带父节点 id + 任务指纹 + 样本类别，
供样本隔离评测与三分归因消费。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# 样本类别：进化样本 vs 验证样本必须隔离（设计单 §4）
SAMPLE_EVOLUTION = "evolution"
SAMPLE_VALIDATION = "validation"
SAMPLE_TRIAL = "trial"
SAMPLE_CLASSES = (SAMPLE_EVOLUTION, SAMPLE_VALIDATION, SAMPLE_TRIAL)

# 三分归因
ATTRIBUTION_CAPABILITY = "capability"       # 专家能力不足
ATTRIBUTION_ROUTING = "routing"             # 路由选择不适配
ATTRIBUTION_ENVIRONMENT = "environment"     # 工具/网关环境问题
ATTRIBUTION_NONE = "none"                   # 成功或无法判定


@dataclass
class ExecutionEvidence:
    """一次真实执行的证据快照（从事件流采集，不伪造）。"""

    id: str
    session_id: str
    task: str
    task_fingerprint: str        # TaskFingerprint.key
    fingerprint_tags: tuple[str, ...]
    sample_class: str            # evolution / validation
    expert_id: str | None        # 本次实际执行的专家节点 id（M1 路由结果）
    parent_id: str | None        # 进化档案中的父节点 id（评测对照用）
    strategy: str                # Core 路由策略 direct/react/plan/clarify
    status: str                  # DONE status: ok / error
    model_calls: int
    standard_calls: int
    strong_calls: int
    usage: dict[str, int]        # token 用量（真实 DONE/budget 快照）
    errors: tuple[dict[str, Any], ...]          # ERROR 事件摘要
    diagnostics: tuple[dict[str, Any], ...]     # DiagnosticEvent 摘要
    tool_calls: tuple[str, ...]                 # 工具名序列（真实 TOOL_CALL 事件）
    verification: dict[str, Any] | None         # OutcomeVerifier 结果（DONE.verification）
    route_decision: dict[str, Any] | None       # M1 真实路由决策快照（expert_id 来源）
    final_text_preview: str
    created_at: str
    trial_id: str = ""                          # R3.2 试用批次
    trial_role: str = ""                        # child / parent（同题成对）

    @classmethod
    def create(cls, **kwargs: Any) -> ExecutionEvidence:
        return cls(
            id=kwargs.pop("id", uuid.uuid4().hex[:12]),
            session_id=kwargs.pop("session_id", ""),
            task=kwargs.pop("task", ""),
            task_fingerprint=kwargs.pop("task_fingerprint", ""),
            fingerprint_tags=tuple(kwargs.pop("fingerprint_tags", ())),
            sample_class=kwargs.pop("sample_class", SAMPLE_EVOLUTION),
            expert_id=kwargs.pop("expert_id", None),
            parent_id=kwargs.pop("parent_id", None),
            strategy=kwargs.pop("strategy", ""),
            status=kwargs.pop("status", ""),
            model_calls=int(kwargs.pop("model_calls", 0)),
            standard_calls=int(kwargs.pop("standard_calls", 0)),
            strong_calls=int(kwargs.pop("strong_calls", 0)),
            usage=dict(kwargs.pop("usage", {})),
            errors=tuple(kwargs.pop("errors", ())),
            diagnostics=tuple(kwargs.pop("diagnostics", ())),
            tool_calls=tuple(kwargs.pop("tool_calls", ())),
            verification=kwargs.pop("verification", None),
            route_decision=kwargs.pop("route_decision", None),
            final_text_preview=str(kwargs.pop("final_text_preview", ""))[:500],
            trial_id=str(kwargs.pop("trial_id", "")),
            trial_role=str(kwargs.pop("trial_role", "")),
            created_at=kwargs.pop("created_at", datetime.now(timezone.utc).isoformat()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "session_id": self.session_id,
            "task": self.task, "task_fingerprint": self.task_fingerprint,
            "fingerprint_tags": list(self.fingerprint_tags),
            "sample_class": self.sample_class,
            "expert_id": self.expert_id, "parent_id": self.parent_id,
            "strategy": self.strategy, "status": self.status,
            "model_calls": self.model_calls,
            "standard_calls": self.standard_calls, "strong_calls": self.strong_calls,
            "usage": dict(self.usage),
            "errors": list(self.errors), "diagnostics": list(self.diagnostics),
            "tool_calls": list(self.tool_calls),
            "verification": self.verification,
            "route_decision": self.route_decision,
            "final_text_preview": self.final_text_preview,
            "trial_id": self.trial_id, "trial_role": self.trial_role,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExecutionEvidence:
        return cls.create(**d)


@dataclass
class FeedbackSignal:
    """用户对一次执行结果的显式反馈（R0：只采集，不触发进化）。

    负向：retract / edit / regenerate；正向：copy / share；中性：continue。
    绑定 evidence_id 与能力标签，供后续能力边界统计使用。
    """

    id: str
    evidence_id: str
    run_id: str
    session_id: str
    kind: str
    polarity: int                      # -1 负向 / 0 中性 / +1 正向
    task_fingerprint: str = ""
    fingerprint_tags: tuple[str, ...] = ()
    note: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "evidence_id": self.evidence_id,
            "run_id": self.run_id, "session_id": self.session_id,
            "kind": self.kind, "polarity": int(self.polarity),
            "task_fingerprint": self.task_fingerprint,
            "fingerprint_tags": list(self.fingerprint_tags),
            "note": self.note, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeedbackSignal":
        return cls(
            id=str(d.get("id", uuid.uuid4().hex[:12])),
            evidence_id=str(d.get("evidence_id", "")),
            run_id=str(d.get("run_id", "")),
            session_id=str(d.get("session_id", "")),
            kind=str(d.get("kind", "")),
            polarity=int(d.get("polarity", 0)),
            task_fingerprint=str(d.get("task_fingerprint", "")),
            fingerprint_tags=tuple(d.get("fingerprint_tags", ())),
            note=str(d.get("note", "")),
            created_at=str(d.get("created_at", "")),
        )


@dataclass
class Attribution:
    """三分归因结论 —— 明确区分三种失败，避免产生无意义分支。"""

    evidence_id: str
    cause: str                         # capability / routing / environment / none
    confidence: float                  # 0..1
    reason: str
    signals: dict[str, Any] = field(default_factory=dict)
    attribution_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribution_id": self.attribution_id,
            "evidence_id": self.evidence_id, "cause": self.cause,
            "confidence": self.confidence, "reason": self.reason,
            "signals": dict(self.signals),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Attribution:
        return cls(
            attribution_id=d.get("attribution_id", uuid.uuid4().hex[:10]),
            evidence_id=d["evidence_id"], cause=d["cause"],
            confidence=float(d.get("confidence", 0.0)),
            reason=d.get("reason", ""), signals=d.get("signals", {}),
        )
