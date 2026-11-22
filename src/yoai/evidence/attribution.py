"""三分归因引擎 · M2 命门。

设计单 §4：必须区分"专家能力不足 / 路由选择不适配 / 工具环境问题"，
避免产生无意义的进化分支。

规则化、可解释、不靠模型自评（诚实原则）：
1. 环境/工具问题：DiagnosticEvent 含 MODEL_TIMEOUT/MODEL_FALLBACK/DISCOVERY_FAILED/
   PROVIDER_ROUTE_BLOCKED/MEMORY_LOAD_FAILED 等；或 ERROR.stage 指向 model/tool/gateway。
2. 能力问题：验收 verified_failure 或 status=error，且无环境诊断信号，且本次确实调了工具
   （执行到位但结果不达成 → 专家能力不够）。
3. 路由不适配：任务失败，但同 fingerprint 的历史证据中其它策略/专家成功过
   （同样的活别人能干 → 选错人/选错策略）。
4. 成功或证据不足 → none（低置信，不硬套归因）。

置信度：按信号强度给分，多信号叠加但封顶 1.0；证据不足时低置信并写明。
"""

from __future__ import annotations

import statistics
from typing import Any

from yoai.evidence.models import (
    ATTRIBUTION_CAPABILITY,
    ATTRIBUTION_ENVIRONMENT,
    ATTRIBUTION_NONE,
    ATTRIBUTION_ROUTING,
    Attribution,
    ExecutionEvidence,
)
from yoai.evidence.store import EvidenceStore

# 环境问题诊断 kind（Core DiagnosticKind 的子集 + 常见字符串）
ENV_DIAGNOSTICS = {
    "model_timeout", "model_error", "model_fallback",
    "discovery_failed", "discoverable_list_failed",
    "provider_route_blocked", "memory_load_failed",
    "host_state_failed", "compaction_fallback", "verification_failed",
}
ENV_ERROR_STAGES = {"model", "tool", "gateway", "llm", "permission"}


class AttributionEngine:
    """把一次执行失败归因到三类原因之一。"""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def attribute(self, evidence: ExecutionEvidence) -> Attribution:
        signals: dict[str, Any] = {}
        env = self._environment_signals(evidence)
        if env:
            signals["environment"] = env
            return Attribution(
                evidence_id=evidence.id, cause=ATTRIBUTION_ENVIRONMENT,
                confidence=min(0.95, 0.6 + 0.12 * len(env)),
                reason="工具/网关环境诊断信号：" + "、".join(env),
                signals=signals,
            )

        ok = self._is_success(evidence)
        if ok:
            return Attribution(
                evidence_id=evidence.id, cause=ATTRIBUTION_NONE,
                confidence=0.9, reason="执行成功，无需归因", signals={"status": evidence.status},
            )

        # 失败：先看同类指纹历史是否有成功者（路由不适配信号）
        routing = self._routing_signals(evidence)
        if routing:
            signals["routing"] = routing
            return Attribution(
                evidence_id=evidence.id, cause=ATTRIBUTION_ROUTING,
                confidence=min(0.9, 0.55 + 0.1 * routing.get("peer_success_count", 0)),
                reason=routing["reason"], signals=signals,
            )

        # 无环境信号、无路由信号、执行失败 → 能力问题（若确实调了工具/有验收结论）
        cap = self._capability_signals(evidence)
        signals["capability"] = cap
        if cap["strong"]:
            return Attribution(
                evidence_id=evidence.id, cause=ATTRIBUTION_CAPABILITY,
                confidence=0.75, reason=cap["reason"], signals=signals,
            )
        # 证据不足：低置信 none，不硬套
        return Attribution(
            evidence_id=evidence.id, cause=ATTRIBUTION_NONE,
            confidence=0.25,
            reason="执行失败但证据不足，无法可靠归因（不生成进化分支）",
            signals=signals,
        )

    # --- 信号检测 ---
    @staticmethod
    def _environment_signals(e: ExecutionEvidence) -> list[str]:
        found: list[str] = []
        for d in e.diagnostics:
            kind = str(d.get("kind", ""))
            if kind in ENV_DIAGNOSTICS:
                found.append(kind)
        for err in e.errors:
            stage = str(err.get("stage", ""))
            if stage in ENV_ERROR_STAGES:
                found.append(f"error:{stage}")
        # 网关 SDK 错误文本里可能出现的关键词（保守，只在 status 非 ok 时）
        if e.status not in ("ok", ""):
            preview = e.final_text_preview
            if "[模型网关错误]" in preview:
                found.append("gateway_error_text")
        return sorted(set(found))

    @staticmethod
    def _is_success(e: ExecutionEvidence) -> bool:
        if e.status == "error":
            return False
        v = e.verification or {}
        status = str(v.get("status", ""))
        if status == "verified_failure":
            return False
        if status == "verified_success":
            return True
        # 无 verifier 时以 status=ok 且无 ERROR 为准（不假装验收过）
        return e.status == "ok" and not e.errors

    def _routing_signals(self, e: ExecutionEvidence) -> dict[str, Any]:
        """同 fingerprint 的历史里，其它 strategy/expert 是否成功过。"""
        peers = [
            x for x in self.store.query(task_fingerprint=e.task_fingerprint)
            if x.id != e.id and self._is_success(x)
        ]
        if not peers:
            return {}
        # 与本节点不同的策略/专家成功 → 选错的可能性高
        different = [
            x for x in peers
            if x.strategy != e.strategy or x.expert_id != e.expert_id
        ]
        if not different:
            return {}
        success_rate = len(different) / max(1, len([
            x for x in self.store.query(task_fingerprint=e.task_fingerprint) if x.id != e.id
        ]))
        return {
            "peer_success_count": len(different),
            "peer_success_rate": round(success_rate, 3),
            "peer_strategies": sorted({x.strategy for x in different}),
            "reason": (
                f"同类任务历史中 {len(different)} 次由其它策略/专家成功完成"
                f"（成功率 {success_rate:.0%}），本次选路可能不适配"
            ),
        }

    @staticmethod
    def _capability_signals(e: ExecutionEvidence) -> dict[str, Any]:
        v = e.verification or {}
        status = str(v.get("status", ""))
        strong = bool(e.tool_calls) or status in ("verified_failure", "partial")
        if status == "verified_failure":
            reason = "验收明确判定失败，且无环境诊断信号 → 专家能力不足"
        elif e.status == "error" and not e.errors:
            reason = "任务错误但无环境诊断 → 疑似专家能力不足"
        else:
            reason = "执行完成但结果不达成（无环境/路由信号）→ 疑似能力不足"
        return {"strong": strong, "reason": reason, "verification_status": status}
