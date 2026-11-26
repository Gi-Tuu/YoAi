"""节能模式专家路由 · M1。

两层路由的边界（重要，别混）：
- Core 的 AdaptiveRouter 决定**怎么执行**：direct / react / plan / clarify。
- 本模块决定**谁执行**：从 EvolutionArchive 的 active 专家里按任务指纹选一个，
  无可靠候选时回退通用根节点。选定后仍由 Core 驱动该专家的执行。

原则：
- 节能模式一次匹配、直接选中，不做试跑（试跑是 M3 最高性能模式的事）。
- 只有 active 节点参与路由；candidate/probation/retired 不参与。
- 每个决策产出 RouteDecision（指纹/候选/理由/回退标记），可审计、可留痕，不静默。
- 零第三方依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.fingerprint import TaskFingerprint, fingerprint
from yoai.evolution.models import ExpertNode

# 打分权重（保守：标签命中是主信号，策略/工具是加分项）
WEIGHT_TAG = 10
WEIGHT_STRATEGY = 3
WEIGHT_TOOL_COVERAGE = 1


@dataclass(frozen=True)
class RouteDecision:
    """一次专家路由决策的完整审计记录。"""

    task: str
    fingerprint: TaskFingerprint
    selected_id: str | None
    selected_name: str
    scores: dict[str, int]          # node_id -> score
    reason: str
    fallback: bool                  # 是否回退根节点
    mode: str = "efficient"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "fingerprint": self.fingerprint.to_dict(),
            "selected_id": self.selected_id,
            "selected_name": self.selected_name,
            "scores": dict(self.scores),
            "reason": self.reason,
            "fallback": self.fallback,
            "mode": self.mode,
        }


class ExpertRouter:
    """专家路由器：节能模式选中 + 根节点回退。"""

    def __init__(
        self,
        archive: EvolutionArchive,
        *,
        tag_lexicon: dict[str, tuple[str, ...]] | None = None,
        mode: str = "efficient",
    ) -> None:
        if mode not in ("efficient", "max_performance"):
            raise ValueError(f"未知路由模式：{mode}")
        self.archive = archive
        self.tag_lexicon = tag_lexicon
        self.mode = mode
        self._last_decision: RouteDecision | None = None
        # R3.2 试用覆盖：(node_id, scope_type, scope_value)；目前支持 tag:<标签>
        self.trial_override: tuple[str, str, str] | None = None

    @property
    def last_decision(self) -> RouteDecision | None:
        return self._last_decision

    def set_trial(self, node_id: str, scope: str) -> None:
        """R3.2：设置试用覆盖。当前支持 tag:<能力标签>。"""
        if not scope.startswith("tag:"):
            raise ValueError("路由试用仅支持 tag:<能力标签>")
        self.trial_override = (node_id, "tag", scope.split(":", 1)[1])

    def clear_trial(self) -> None:
        self.trial_override = None

    @property
    def trial_node_id(self) -> str:
        return self.trial_override[0] if self.trial_override else ""

    def route(self, task: str) -> RouteDecision:
        """为任务选择一个 active 专家；无可靠候选回退根节点。

        根节点也没有时返回 selected_id=None（明确失败，不假装选中）。
        """
        fp = fingerprint(task, tag_lexicon=self.tag_lexicon)

        if self.trial_override:
            node_id, scope_type, scope_value = self.trial_override
            node = self.archive.get(node_id)
            if node is None or node.lifecycle != "probation":
                self.clear_trial()
            elif scope_type == "tag" and scope_value in fp.tags:
                decision = RouteDecision(
                    task=task, fingerprint=fp, selected_id=node.id,
                    selected_name=node.name, scores={},
                    reason=f"R3.2 试用覆盖：命中标签 {scope_value}", fallback=False,
                )
                self._last_decision = decision
                return decision

        if self.mode == "max_performance":
            raise NotImplementedError(
                "最高性能模式（预算内候选试验）属 M3，尚未实现；请用 efficient 模式"
            )

        candidates = self.archive.routing_candidates()
        scores: dict[str, int] = {}
        for node in candidates:
            scores[node.id] = self._score(node, fp)

        best_id = self._best(scores)

        # 无可靠候选（没有任何 active 节点得分 > 0）→ 回退 active 根节点
        fallback = False
        if best_id is None or scores[best_id] <= 0:
            root = self.archive.root
            if root and root.lifecycle == "active":
                best_id = root.id
                fallback = True
                reason = f"无可靠候选（最高分≤0），回退通用根节点：{root.name}"
            else:
                decision = RouteDecision(
                    task=task, fingerprint=fp, selected_id=None,
                    selected_name="", scores=scores,
                    reason="无可靠候选且无 active 根节点，路由失败",
                    fallback=False,
                )
                self._last_decision = decision
                return decision
        else:
            node = self.archive.get(best_id)
            reason = (
                f"命中能力标签 {tuple(sorted(set(fp.tags) & set(node.spec.capability_tags)))}，"
                f"得分 {scores[best_id]}"
            )

        node = self.archive.get(best_id)
        decision = RouteDecision(
            task=task, fingerprint=fp, selected_id=best_id,
            selected_name=node.name if node else "",
            scores=scores, reason=reason, fallback=fallback,
        )
        self._last_decision = decision
        return decision

    # --- 打分 ---
    def _score(self, node: ExpertNode, fp: TaskFingerprint) -> int:
        score = 0
        # 能力标签交集（主信号）
        overlap = set(fp.tags) & set(node.spec.capability_tags)
        score += WEIGHT_TAG * len(overlap)
        # 策略偏好 vs 结构信号
        bias = node.spec.strategy_bias
        if bias:
            signal_map = {
                "plan": "multi_step",
                "react": "action",
                "clarify": "vague",
                "direct": "question",
            }
            if signal_map.get(bias) in fp.signals:
                score += WEIGHT_STRATEGY
        # 工具覆盖（弱信号：指纹命中标签对应的默认工具在白名单里）
        score += WEIGHT_TOOL_COVERAGE * len(
            set(fp.tags) & {t.replace("_tool", "") for t in node.spec.tools}
        )
        return score

    @staticmethod
    def _best(scores: dict[str, int]) -> str | None:
        """确定性选优：分数高者优先，同分按 node_id 字典序（保证可复现）。"""
        if not scores:
            return None
        return sorted(
            scores.keys(),
            key=lambda k: (-scores[k], k),
        )[0]


class ForcedExpertRouter(ExpertRouter):
    """R3.3：后台影子运行强制指定节点（parent shadow）。不参与正常 UI 路由。"""

    def __init__(self, archive: EvolutionArchive, node_id: str,
                 tag_lexicon=None) -> None:
        super().__init__(archive, tag_lexicon=tag_lexicon)
        self.node_id = node_id

    def route(self, task: str) -> RouteDecision:
        node = self.archive.get(self.node_id)
        fp = fingerprint(task, tag_lexicon=self.tag_lexicon)
        decision = RouteDecision(
            task=task, fingerprint=fp,
            selected_id=node.id if node else None,
            selected_name=node.name if node else "",
            scores={}, reason="R3.3 parent shadow（后台对照，不展示）",
            fallback=False,
        )
        self._last_decision = decision
        return decision
