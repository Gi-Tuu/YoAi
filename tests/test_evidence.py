"""证据基础设施测试：采集/归因/样本隔离/Wilson/持久化。离线、零依赖。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.types import AgentEvent, EventType  # noqa: E402

from yoai.evidence import (  # noqa: E402
    ATTRIBUTION_CAPABILITY, ATTRIBUTION_ENVIRONMENT,
    ATTRIBUTION_NONE, ATTRIBUTION_ROUTING,
    SAMPLE_EVOLUTION, SAMPLE_VALIDATION,
    AttributionEngine, BenchmarkLab, EvidenceStore,
    ExecutionEvidenceCollector, wilson_interval,
)


def _done(**overrides):
    data = {
        "strategy": "react", "status": "ok", "final_text": "回答文本",
        "model_calls": 2, "standard_calls": 2, "strong_calls": 0,
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    data.update(overrides)
    return AgentEvent(EventType.DONE, data)


def _evidence(store, eid, *, fingerprint="fp1", expert="e1", strategy="react",
              status="ok", sample=SAMPLE_EVOLUTION, diagnostics=(), errors=(),
              tools=(), verification=None):
    from yoai.evidence import ExecutionEvidence
    ev = ExecutionEvidence.create(
        id=eid, session_id="s", task="t", task_fingerprint=fingerprint,
        fingerprint_tags=("writing",), sample_class=sample,
        expert_id=expert, parent_id="parent", strategy=strategy, status=status,
        diagnostics=list(diagnostics), errors=list(errors), tool_calls=list(tools),
        verification=verification,
    )
    store.add(ev)
    return ev


class FakeDiag:
    def __init__(self, kind, message=""):
        self.kind, self.message, self.level, self.data = kind, message, "warning", {}


# --- 采集 ---
def test_collector_extracts_done_fields():
    c = ExecutionEvidenceCollector()
    c.observe(_done())
    ev = c.finish(session_id="s", task="写总结", task_fingerprint="k",
                  fingerprint_tags=("writing",), sample_class=SAMPLE_EVOLUTION,
                  expert_id="e1", parent_id="p")
    assert ev.strategy == "react" and ev.status == "ok"
    assert ev.model_calls == 2 and ev.usage["total_tokens"] == 150
    assert ev.final_text_preview == "回答文本"


def test_collector_extracts_error_tool_diagnostic():
    c = ExecutionEvidenceCollector()
    c.observe(AgentEvent(EventType.TOOL_CALL, {"tool": "remember_fact"}))
    c.observe(AgentEvent(EventType.ERROR, {"stage": "model", "error": "timeout"}))
    c.observe_diagnostic(FakeDiag("model_timeout", "模型超时"))
    c.observe(_done(status="error"))
    ev = c.finish(session_id="s", task="t", task_fingerprint="k",
                  fingerprint_tags=(), sample_class=SAMPLE_EVOLUTION,
                  expert_id=None, parent_id=None)
    assert ev.tool_calls == ("remember_fact",)
    assert ev.errors[0]["stage"] == "model"
    assert ev.diagnostics[0]["kind"] == "model_timeout"


def test_collector_verification_from_done():
    c = ExecutionEvidenceCollector()
    c.observe(_done(verification={"status": "verified_success", "confidence": 0.9}))
    ev = c.finish(session_id="s", task="t", task_fingerprint="k",
                  fingerprint_tags=(), sample_class=SAMPLE_VALIDATION,
                  expert_id="e", parent_id="p")
    assert ev.verification["status"] == "verified_success"


def test_collector_usage_override():
    """事件流无 usage 时，宿主可传真实 provider 累计用量。"""
    c = ExecutionEvidenceCollector()
    c.observe(_done(usage={}))  # DONE 无 usage
    ev = c.finish(session_id="s", task="t", task_fingerprint="k",
                  fingerprint_tags=(), sample_class=SAMPLE_EVOLUTION,
                  expert_id="e", parent_id="p",
                  usage_override={"prompt_tokens": 10, "total_tokens": 20})
    assert ev.usage["total_tokens"] == 20


# --- 归因 ---
def test_attribution_environment(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    ev = _evidence(store, "e1", status="error", diagnostics=[{"kind": "model_timeout", "message": "超时"}])
    a = AttributionEngine(store).attribute(ev)
    assert a.cause == ATTRIBUTION_ENVIRONMENT and a.confidence > 0.6


def test_attribution_capability(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    ev = _evidence(store, "e1", status="ok", tools=("remember_fact",),
                   verification={"status": "verified_failure"})
    a = AttributionEngine(store).attribute(ev)
    assert a.cause == ATTRIBUTION_CAPABILITY


def test_attribution_routing(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    # 同类指纹：别人用 plan+expert2 成功过
    _evidence(store, "peer", fingerprint="fp1", expert="e2", strategy="plan",
              verification={"status": "verified_success"})
    ev = _evidence(store, "fail", fingerprint="fp1", expert="e1", strategy="react",
                   verification={"status": "verified_failure"})
    a = AttributionEngine(store).attribute(ev)
    assert a.cause == ATTRIBUTION_ROUTING


def test_attribution_success_is_none(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    ev = _evidence(store, "ok", verification={"status": "verified_success"})
    a = AttributionEngine(store).attribute(ev)
    assert a.cause == ATTRIBUTION_NONE and a.confidence >= 0.9


def test_attribution_insufficient_low_confidence(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    ev = _evidence(store, "x", status="error", errors=[])  # 失败但无信号
    a = AttributionEngine(store).attribute(ev)
    assert a.cause == ATTRIBUTION_NONE and a.confidence < 0.5


def test_attribution_persists(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    ev = _evidence(store, "e1", status="error", diagnostics=[{"kind": "model_timeout"}])
    a = AttributionEngine(store).attribute(ev)
    store.add_attribution(a)
    store2 = EvidenceStore(tmp_path / "e.json")
    assert store2.attribution_for("e1").cause == ATTRIBUTION_ENVIRONMENT


# --- 样本隔离与评测 ---
def test_validation_set_isolated(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    _evidence(store, "ev", sample=SAMPLE_EVOLUTION)
    _evidence(store, "va", sample=SAMPLE_VALIDATION)
    assert {e.id for e in store.validation_set()} == {"va"}


def test_wilson_interval_basic():
    lo, hi = wilson_interval(8, 10)
    assert 0 <= lo <= 0.8 <= hi <= 1
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_benchmark_insufficient_samples(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    _evidence(store, "v1", expert="cand", sample=SAMPLE_VALIDATION,
              verification={"status": "verified_success"})
    report = BenchmarkLab(store, min_samples=3).evaluate("cand", "parent")
    assert report.verdict == "insufficient" and report.total_samples == 1


def test_benchmark_never_uses_evolution_samples(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    for i in range(5):
        _evidence(store, f"ev{i}", expert="cand", sample=SAMPLE_EVOLUTION,
                  verification={"status": "verified_failure"})
    report = BenchmarkLab(store, min_samples=3).evaluate("cand", "parent")
    assert report.total_samples == 0  # 进化样本不进验证


def test_benchmark_reports_boundaries(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    for i in range(4):
        _evidence(store, f"c{i}", expert="cand", sample=SAMPLE_VALIDATION,
                  verification={"status": "verified_success"})
        _evidence(store, f"p{i}", expert="parent", sample=SAMPLE_VALIDATION,
                  verification={"status": "verified_failure"})
    report = BenchmarkLab(store, min_samples=3).evaluate("cand", "parent")
    assert report.verdict == "improved"
    b = report.boundaries[0]
    assert b.node_rate == 1.0 and b.parent_rate == 0.0 and b.sample_enough


# --- 持久化 ---
def test_store_persists_across_sessions(tmp_path):
    store = EvidenceStore(tmp_path / "e.json")
    _evidence(store, "x")
    store2 = EvidenceStore(tmp_path / "e.json")
    assert store2.count() == 1 and store2.get("x").task_fingerprint == "fp1"


def test_corrupt_store_isolated(tmp_path):
    p = tmp_path / "e.json"
    p.write_text("{bad", encoding="utf-8")
    store = EvidenceStore(p)
    assert store.count() == 0 and p.with_suffix(".json.corrupt").exists()
