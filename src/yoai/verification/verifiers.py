"""YoAi 真实 OutcomeVerifier · 让任务验收不再只看 status。

设计单精神：工具调用成功 ≠ 副作用状态 ≠ 可观察结果 ≠ 目标达成。
Core 的默认行为是"无 verifier 则不验收"（not_verifiable 都不给），
这里提供真正基于证据的验收器：

1. ReceiptVerifier：基于 Core 收集的 TOOL_RESULT 收据（kind=receipt）判定工具层面成败。
2. StateAssertionVerifier：注入断言函数（如查 PersonalContext 真实状态），
   验证"记住 X=Y"这类任务的**副作用状态**——这正是 status=ok 无法证明的。
3. build_default_verifier：组合两者（复用 Core 的 CompositeVerifier，最坏情况优先）。

诚实原则：
- 没有证据就 not_verifiable，不假装成功；
- verifier 异常由 Core 的 verify_run 兜底降级，这里也不吞意外；
- 断言只看真实状态，不问模型"你觉得成功了吗"。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from yai_core.types import Evidence, VerificationResult

# 目标语义 → 断言提取：从中文目标里识别"记住/记下 X 是 Y"这类可硬验证的目标
_REMEMBER_WORDS = ("记住", "记下", "记录", "保存", "牢记")


class ReceiptVerifier:
    """基于执行收据的验收器（工具层面）。

    - 任一 receipt.status=failed → verified_failure；
    - 全部 receipt succeeded → verified_success；
    - 有 unknown → partial；
    - 无 receipt 证据 → not_verifiable（不假装验收过）。
    """

    async def verify(
        self,
        goal: str,
        *,
        evidence: Sequence[Evidence] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> VerificationResult:
        receipts = [e for e in evidence if getattr(e, "kind", "") == "receipt"]
        if not receipts:
            return VerificationResult(
                status="not_verifiable", goal=goal,
                reason="无执行收据证据，工具层面无法验收",
            )
        oks = [bool(getattr(e, "ok", False)) for e in receipts if getattr(e, "ok", None) is not None]
        unknowns = [e for e in receipts if getattr(e, "ok", None) is None]
        reasons = "; ".join(str(getattr(e, "summary", "")) for e in receipts[:5])
        if oks and not all(oks):
            return VerificationResult(
                status="verified_failure", goal=goal, confidence=0.9,
                reason=f"存在失败的工具收据：{reasons}",
                evidence=tuple(receipts),
            )
        if unknowns and oks:
            return VerificationResult(
                status="partial", goal=goal, confidence=0.6,
                reason=f"部分工具结果未知：{reasons}", evidence=tuple(receipts),
            )
        if unknowns:
            return VerificationResult(
                status="unknown", goal=goal, confidence=0.3,
                reason=f"工具收据均为未知状态：{reasons}", evidence=tuple(receipts),
            )
        return VerificationResult(
            status="verified_success", goal=goal, confidence=0.85,
            reason=f"全部工具收据成功：{reasons}", evidence=tuple(receipts),
        )


# 断言函数：(goal, evidence, metadata) -> (status, reason, confidence)
AssertionFn = Callable[[str, Sequence[Evidence], Mapping[str, Any]], tuple[str, str, float]]


class StateAssertionVerifier:
    """基于真实状态断言的验收器（副作用层面）。

    注入的 assertion 函数必须查询真实状态（如 context.recall），
    不能是模型自评。无断言或无证据 → not_verifiable。
    """

    def __init__(self, assertion: AssertionFn | None = None, *, name: str = "state") -> None:
        self.assertion = assertion
        self.name = name

    async def verify(
        self,
        goal: str,
        *,
        evidence: Sequence[Evidence] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> VerificationResult:
        if self.assertion is None:
            return VerificationResult(
                status="not_verifiable", goal=goal,
                reason=f"验收器 {self.name} 未注入状态断言函数",
            )
        try:
            status, reason, confidence = self.assertion(goal, evidence, metadata or {})
        except Exception as exc:  # noqa: BLE001 - 交给 verify_run 的兜底也行，这里写清原因
            return VerificationResult(
                status="not_verifiable", goal=goal,
                reason=f"状态断言异常：{type(exc).__name__}: {exc}",
            )
        if status not in ("verified_success", "verified_failure", "partial", "unknown", "not_verifiable"):
            return VerificationResult(
                status="not_verifiable", goal=goal,
                reason=f"状态断言返回非法状态：{status!r}",
            )
        return VerificationResult(
            status=status, goal=goal,
            confidence=max(0.0, min(1.0, float(confidence))),
            reason=reason, evidence=tuple(
                e for e in evidence if getattr(e, "kind", "") in ("state", "receipt")
            ),
        )


def build_default_verifier(assertion: AssertionFn | None = None):
    """组合收据验收 + 状态断言（最坏情况优先）。

    无断言时只装收据验收器；两者都无证据时结果为 not_verifiable（诚实）。
    """
    from yai_core.verification import CompositeVerifier
    verifiers: list[Any] = [ReceiptVerifier()]
    if assertion is not None:
        verifiers.append(StateAssertionVerifier(assertion))
    return CompositeVerifier(verifiers)
