"""RSI R2.1 shadow 触发引擎（YoAi 侧，内核零改动）。

输入：R1 能力边界报告 + 执行证据 + 归因结论。
输出：candidate 节点（只写档案、不进路由、不晋升）与可审计触发决策。

安全规则：
- 只对 weak 边界触发；watch 只记录观察，不改能力。
- 样本/归因/冷却三条硬门槛，任缺不生成候选。
- 一次只改一个能力维度（工具或提示/标签），diff 写明来源。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from yoai.evidence.boundary import BoundaryReport, BoundaryRow
from yoai.evidence.models import (
    ATTRIBUTION_CAPABILITY,
    ATTRIBUTION_ENVIRONMENT,
    ATTRIBUTION_ROUTING,
    ExecutionEvidence,
)
from yoai.evidence.store import EvidenceStore
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.models import EvidenceRef, ExpertSpec
from yoai.evolution.reports import EvolutionReportStore

COOLDOWN_DAYS = 7
MIN_ATTRIBUTION_RATIO = 0.60
MAX_ENVIRONMENT_RATIO = 0.20


@dataclass
class TriggerDecision:
    tag: str
    created: bool
    reason: str
    node_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "created": self.created,
                "reason": self.reason, "node_id": self.node_id}


class TriggerEngine:
    def __init__(
        self,
        archive: EvolutionArchive,
        evidence_store: EvidenceStore,
        report_store: EvolutionReportStore,
        *,
        cooldown_days: int = COOLDOWN_DAYS,
    ) -> None:
        self.archive = archive
        self.store = evidence_store
        self.reports = report_store
        self.cooldown_days = cooldown_days

    def evaluate(
        self, report: BoundaryReport, *, tags: list[str] | None = None
    ) -> list[TriggerDecision]:
        decisions: list[TriggerDecision] = []
        wanted = set(tags or [])
        for row in report.rows:
            if wanted and row.tag not in wanted:
                continue
            decisions.append(self._evaluate_row(row))
        return decisions

    def _evaluate_row(self, row: BoundaryRow) -> TriggerDecision:
        if row.status != "weak" or not row.sample_enough:
            return TriggerDecision(row.tag, False,
                                   f"边界状态 {row.status}，不满足 shadow 触发条件")

        if self._in_cooldown(row.tag):
            return TriggerDecision(row.tag, False,
                                   f"{self.cooldown_days} 天内已有同方向候选，冷却中")

        items = [e for e in self.store.query() if row.tag in e.fingerprint_tags]
        if len(items) < row.total:
            return TriggerDecision(row.tag, False, "证据与看板样本不一致，跳过")
        causes = [self.store.attribution_for(e.id) for e in items]
        causes = [a for a in causes if a is not None]
        if not causes:
            return TriggerDecision(row.tag, False, "缺少归因结论，不凭边界分数盲改")
        capability = sum(1 for a in causes if a.cause in (ATTRIBUTION_CAPABILITY, ATTRIBUTION_ROUTING))
        environment = sum(1 for a in causes if a.cause == ATTRIBUTION_ENVIRONMENT)
        if capability / len(causes) < MIN_ATTRIBUTION_RATIO:
            return TriggerDecision(row.tag, False,
                                   f"能力/路由归因仅 {capability}/{len(causes)}，不足 60%")
        if environment / len(causes) >= MAX_ENVIRONMENT_RATIO:
            return TriggerDecision(row.tag, False,
                                   f"环境归因占比 {environment}/{len(causes)} 过高")

        parent = self._parent_for(items)
        if parent is None:
            return TriggerDecision(row.tag, False, "找不到父节点，跳过")
        spec, diff, reason = self._one_dimension_spec(parent.spec, items, row, causes)
        node = self.archive.create_child(parent.id, f"{parent.name}·{row.tag}候选",
                                         spec, diff=diff)
        self.archive.add_evidence(node.id, EvidenceRef(
            id=f"trigger-{node.id}", kind="rsi_trigger",
            task_fingerprint=row.tag, outcome="candidate",
            detail=f"{row.tag} 边界薄弱，生成 shadow 候选；未进入路由",
        ))
        self.reports.add({
            "id": f"trg-{node.id}", "evidence_id": "", "triggered": True,
            "cause": "rsi_shadow_trigger", "new_node_id": node.id,
            "reason": reason, "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "rsi_trigger", "tag": row.tag,
        })
        return TriggerDecision(row.tag, True, reason, node.id)

    def _in_cooldown(self, tag: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cooldown_days)
        for node in self.archive.list_nodes():
            if node.lifecycle not in ("candidate", "probation"):
                continue
            if str(node.diff.get("tag", "")) != tag and tag not in node.spec.capability_tags:
                continue
            try:
                created = datetime.fromisoformat(node.created_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= cutoff:
                return True
        return False

    def _parent_for(self, items: list[ExecutionEvidence]) -> Any:
        for item in reversed(items):
            if item.expert_id:
                node = self.archive.get(item.expert_id)
                if node is not None:
                    return node
        return self.archive.root

    @staticmethod
    def _one_dimension_spec(
        parent: ExpertSpec, items: list[ExecutionEvidence],
        row: BoundaryRow, causes: list[Any],
    ) -> tuple[ExpertSpec, dict[str, Any], str]:
        capability_cause = sum(1 for a in causes
                               if a.cause == ATTRIBUTION_CAPABILITY)
        if capability_cause >= len(causes) / 2:
            used = sorted({tool for item in items for tool in item.tool_calls
                           if tool and tool not in parent.tools})
            if used:
                spec = replace(parent, tools=tuple(sorted(set(parent.tools) | set(used))))
                diff = {"dimension": "tools", "tag": row.tag,
                        "tools_added": used, "rework_rate": row.rework_rate}
                reason = (f"{row.tag} 返工率 {row.rework_rate:.0%}，能力归因；"
                          f"shadow 候选仅补工具：{', '.join(used)}")
                return spec, diff, reason
            spec = replace(parent, prompt_suffix="\n".join(
                s for s in (parent.prompt_suffix, "执行前先核对同类任务的已知约束。") if s))
            diff = {"dimension": "prompt", "tag": row.tag,
                    "prompt_added": "执行前先核对同类任务的已知约束。",
                    "rework_rate": row.rework_rate}
            reason = f"{row.tag} 返工率 {row.rework_rate:.0%}，能力归因；shadow 候选仅补提示"
            return spec, diff, reason

        tags = sorted(set(parent.capability_tags) | {row.tag})
        spec = replace(parent, capability_tags=tuple(tags))
        diff = {"dimension": "capability_tags", "tag": row.tag,
                "tags_added": sorted({row.tag} - set(parent.capability_tags)),
                "rework_rate": row.rework_rate}
        reason = f"{row.tag} 返工率 {row.rework_rate:.0%}，路由归因；shadow 候选仅补能力标签"
        return spec, diff, reason
