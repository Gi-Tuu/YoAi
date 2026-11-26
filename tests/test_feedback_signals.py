"""RSI R0 反馈信号守护测试：只采集，不触发进化。"""

from __future__ import annotations

from yoai.evidence import FeedbackSignal, FeedbackStore


def test_feedback_store_roundtrip(tmp_path):
    store = FeedbackStore(tmp_path)
    signal = FeedbackSignal(
        id="f1", evidence_id="e1", run_id="r1", session_id="s1",
        kind="regenerate", polarity=-1, task_fingerprint="fp1",
        fingerprint_tags=("temporal",), note="用户重新生成",
    )
    assert store.add(signal) == "f1"
    assert store.count() == 1
    items = store.list(evidence_id="e1")
    assert len(items) == 1 and items[0].kind == "regenerate" and items[0].polarity == -1
    assert store.list(kind="copy") == []


def test_corrupt_feedback_log_is_not_fatal(tmp_path):
    path = tmp_path / "evidence" / "feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("坏行\n", encoding="utf-8")
    assert FeedbackStore(tmp_path).count() == 0
