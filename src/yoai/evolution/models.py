"""进化档案的数据模型 · M0。

核心契约（见 docs/EVOLUTION-PLAN.md §3，待用户确认）：
- 专家 = 轻量能力配置，不是完整 Agent 实例。
- 字段只含"能力切面"：工具白名单、策略偏好、提示词片段、model tier、预算、能力标签。
- **不含**个人记忆、人格、会话历史——这些由运行时外层共享注入，不随分支复制。
- 生命周期单向：candidate → probation → active → retired；retired 为终态但保留档案。
- 恢复点（Checkpoint）是节点配置 + 依赖版本 + 血统 + 证据索引的不可变快照。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal

Lifecycle = Literal["candidate", "probation", "active", "retired"]

# 单向迁移表；retired 终态（不复活，恢复走新节点，见 EVOLUTION-PLAN §6 待拍板）
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "candidate": ("probation", "retired"),
    "probation": ("active", "retired"),
    "active": ("retired",),
    "retired": (),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExpertSpec:
    """专家的轻量能力配置（能力切面，不含人格与记忆）。"""

    tools: tuple[str, ...] = ()              # 工具白名单
    strategy_bias: str = ""                  # 策略偏好：direct/react/plan/clarify
    prompt_suffix: str = ""                  # 提示词片段（能力导向，非人格）
    model_tier: str = "standard"             # standard / strong
    budget: dict[str, int] | None = None     # 可选预算上限
    capability_tags: tuple[str, ...] = ()    # 能力标签，供路由指纹匹配

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": list(self.tools),
            "strategy_bias": self.strategy_bias,
            "prompt_suffix": self.prompt_suffix,
            "model_tier": self.model_tier,
            "budget": dict(self.budget) if self.budget else None,
            "capability_tags": list(self.capability_tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpertSpec:
        return cls(
            tools=tuple(data.get("tools", [])),
            strategy_bias=data.get("strategy_bias", ""),
            prompt_suffix=data.get("prompt_suffix", ""),
            model_tier=data.get("model_tier", "standard"),
            budget=data.get("budget"),
            capability_tags=tuple(data.get("capability_tags", [])),
        )


@dataclass(frozen=True)
class EvidenceRef:
    """一条历史证据的索引（不内嵌大对象，只存引用与摘要）。"""

    id: str
    kind: str            # regression / unseen / boundary / trial
    task_fingerprint: str
    outcome: str         # pass / fail / partial
    detail: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind,
            "task_fingerprint": self.task_fingerprint,
            "outcome": self.outcome, "detail": self.detail,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRef:
        return cls(
            id=data["id"], kind=data.get("kind", ""),
            task_fingerprint=data.get("task_fingerprint", ""),
            outcome=data.get("outcome", ""), detail=data.get("detail", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class ExpertNode:
    """进化树中的一个专家节点。"""

    id: str
    name: str
    version: int                              # 全局递增版本号
    parent_id: str | None                     # 根节点为 None
    lifecycle: Lifecycle
    spec: ExpertSpec
    diff: dict[str, Any]                      # 相对父节点的修改差异（根节点为空）
    dependencies: dict[str, str]              # Core/YoAi 版本、模型等
    evidence: list[EvidenceRef]               # 历史证据索引
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        name: str,
        version: int,
        spec: ExpertSpec,
        *,
        parent_id: str | None = None,
        diff: dict[str, Any] | None = None,
        dependencies: dict[str, str] | None = None,
        lifecycle: Lifecycle = "candidate",
    ) -> ExpertNode:
        now = _now()
        return cls(
            id=uuid.uuid4().hex[:10],
            name=name,
            version=version,
            parent_id=parent_id,
            lifecycle=lifecycle,
            spec=spec,
            diff=dict(diff or {}),
            dependencies=dict(dependencies or {}),
            evidence=[],
            created_at=now,
            updated_at=now,
        )

    def can_transition(self, target: str) -> bool:
        return target in TRANSITIONS.get(self.lifecycle, ())

    def transition(self, target: str) -> bool:
        """状态迁移；非法迁移返回 False 且不改状态。retired 终态。"""
        if not self.can_transition(target):
            return False
        self.lifecycle = target  # type: ignore[assignment]
        self.updated_at = _now()
        return True

    def add_evidence(self, evidence: EvidenceRef) -> None:
        self.evidence.append(evidence)
        self.updated_at = _now()

    def checkpoint(self) -> Checkpoint:
        """生成不可变恢复点快照。"""
        return Checkpoint(
            node_id=self.id,
            name=self.name,
            version=self.version,
            parent_id=self.parent_id,
            spec=replace(self.spec),
            dependencies=dict(self.dependencies),
            evidence_ids=tuple(e.id for e in self.evidence),
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "parent_id": self.parent_id, "lifecycle": self.lifecycle,
            "spec": self.spec.to_dict(), "diff": dict(self.diff),
            "dependencies": dict(self.dependencies),
            "evidence": [e.to_dict() for e in self.evidence],
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpertNode:
        return cls(
            id=data["id"], name=data["name"], version=data["version"],
            parent_id=data.get("parent_id"),
            lifecycle=data.get("lifecycle", "candidate"),  # type: ignore[assignment]
            spec=ExpertSpec.from_dict(data.get("spec", {})),
            diff=data.get("diff", {}),
            dependencies=data.get("dependencies", {}),
            evidence=[EvidenceRef.from_dict(e) for e in data.get("evidence", [])],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass(frozen=True)
class Checkpoint:
    """恢复点：节点在某个时刻的不可变配置快照。

    不含个人记忆/人格/会话历史；这些由运行时共享注入。
    """

    node_id: str
    name: str
    version: int
    parent_id: str | None
    spec: ExpertSpec
    dependencies: dict[str, str]
    evidence_ids: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "name": self.name,
            "version": self.version, "parent_id": self.parent_id,
            "spec": self.spec.to_dict(),
            "dependencies": dict(self.dependencies),
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            node_id=data["node_id"], name=data.get("name", ""),
            version=data.get("version", 0), parent_id=data.get("parent_id"),
            spec=ExpertSpec.from_dict(data.get("spec", {})),
            dependencies=data.get("dependencies", {}),
            evidence_ids=tuple(data.get("evidence_ids", [])),
            created_at=data.get("created_at", ""),
        )
