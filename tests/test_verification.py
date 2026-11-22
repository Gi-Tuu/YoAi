"""真实验收器测试：收据判定、状态断言、组合器、证据链闭环。离线。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:\Competition\YAI Agent Core") / "src"))

from yai_core.types import Evidence  # noqa: E402

from yoai.verification import (  # noqa: E402
    ReceiptVerifier, StateAssertionVerifier, build_default_verifier,
    make_context_assertion,
)


def _receipt(tool, status, ok):
    return Evidence(kind="receipt", summary=f"{tool}: {status}", ok=ok,
                    detail={"tool": tool, "status": status})


# --- ReceiptVerifier ---
def test_receipt_all_success():
    r = asyncio.run(ReceiptVerifier().verify("t", evidence=[_receipt("a", "succeeded", True)]))
    assert r.status == "verified_success" and r.confidence > 0.8


def test_receipt_any_failed():
    r = asyncio.run(ReceiptVerifier().verify("t", evidence=[
        _receipt("a", "succeeded", True), _receipt("b", "failed", False),
    ]))
    assert r.status == "verified_failure" and "失败" in r.reason


def test_receipt_unknown():
    r = asyncio.run(ReceiptVerifier().verify("t", evidence=[
        Evidence(kind="receipt", summary="a: unknown", ok=None),
    ]))
    assert r.status == "unknown"


def test_receipt_no_evidence():
    r = asyncio.run(ReceiptVerifier().verify("t", evidence=[]))
    assert r.status == "not_verifiable"  # 无证据不假装成功


# --- StateAssertionVerifier ---
class FakeContext:
    def __init__(self, facts):
        self._facts = facts

    def list_all(self):
        return self._facts


def test_context_assertion_success():
    ctx = FakeContext({"城市": "杭州"})
    v = StateAssertionVerifier(make_context_assertion(ctx))
    r = asyncio.run(v.verify("记住我的城市是杭州", evidence=[_receipt("remember_fact", "succeeded", True)]))
    assert r.status == "verified_success" and "杭州" in r.reason


def test_context_assertion_failure_catches_false_claim():
    """模型说记住了但状态没落盘 → 硬判失败（验收器的核心价值）。"""
    ctx = FakeContext({})
    v = StateAssertionVerifier(make_context_assertion(ctx))
    r = asyncio.run(v.verify("记住我的城市是杭州", evidence=[_receipt("remember_fact", "succeeded", True)]))
    assert r.status == "verified_failure"


def test_context_assertion_no_memory_intent():
    ctx = FakeContext({"城市": "杭州"})
    v = StateAssertionVerifier(make_context_assertion(ctx))
    r = asyncio.run(v.verify("今天天气如何", evidence=[]))
    assert r.status == "not_verifiable"  # 无可验意图，跳过


def test_assertion_no_fn():
    v = StateAssertionVerifier(None)
    r = asyncio.run(v.verify("记住X", evidence=[]))
    assert r.status == "not_verifiable"


def test_assertion_exception_is_safe():
    def bad(goal, evidence, meta):
        raise RuntimeError("boom")
    v = StateAssertionVerifier(bad)
    r = asyncio.run(v.verify("记住X", evidence=[]))
    assert r.status == "not_verifiable" and "boom" in r.reason


def test_assertion_illegal_status():
    v = StateAssertionVerifier(lambda g, e, m: ("success", "bad", 1.0))
    r = asyncio.run(v.verify("记住X", evidence=[]))
    assert r.status == "not_verifiable" and "非法状态" in r.reason


# --- 组合器 ---
def test_composite_worst_case_priority():
    ctx = FakeContext({})  # 状态未落盘
    verifier = build_default_verifier(make_context_assertion(ctx))
    # 收据成功但状态断言失败 → 组合取失败（最坏优先）
    r = asyncio.run(verifier.verify("记住城市是杭州", evidence=[_receipt("remember_fact", "succeeded", True)]))
    assert r.status == "verified_failure"


def test_composite_both_success():
    ctx = FakeContext({"城市": "杭州"})
    verifier = build_default_verifier(make_context_assertion(ctx))
    r = asyncio.run(verifier.verify("记住城市是杭州", evidence=[_receipt("remember_fact", "succeeded", True)]))
    assert r.status == "verified_success"


def test_composite_no_assertion_only_receipt():
    verifier = build_default_verifier(None)
    r = asyncio.run(verifier.verify("t", evidence=[_receipt("a", "succeeded", True)]))
    assert r.status == "verified_success"


def test_attribution_uses_hard_verification_not_status(tmp_path):
    """关键：status=ok 但 verified_failure 时，归因不能当成功。"""
    from yoai.evidence import EvidenceStore, AttributionEngine, ExecutionEvidence, ATTRIBUTION_CAPABILITY

    store = EvidenceStore(tmp_path / "e.json")
    ev = ExecutionEvidence.create(
        session_id="s", task="记住城市", task_fingerprint="k",
        fingerprint_tags=("memory",), sample_class="evolution",
        expert_id="e", parent_id=None, strategy="direct", status="ok",
        tool_calls=(),  # 谎称：没调工具
        verification={"status": "verified_failure", "reason": "状态未落盘"},
    )
    store.add(ev)
    a = AttributionEngine(store).attribute(ev)
    assert a.cause != "none"  # 不能当成功放过
