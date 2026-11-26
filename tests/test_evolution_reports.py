"""进化报告持久化守护测试。"""

from __future__ import annotations

from yoai.evolution import EvolutionReportStore


def test_report_store_roundtrip_and_node_filter(tmp_path):
    store = EvolutionReportStore(tmp_path)
    common = {
        "id": "r1", "evidence_id": "e1", "triggered": True,
        "cause": "capability", "new_node_id": "n1", "reason": "候选已创建",
        "created_at": "2026-11-26T00:00:00Z",
    }
    store.add(common)
    store.add({**common, "id": "r2", "new_node_id": "n2"})
    assert len(store.list()) == 2
    assert [r["id"] for r in store.list("n1")] == ["r1"]


def test_corrupt_report_log_is_not_fatal(tmp_path):
    path = tmp_path / "evolution" / "reports.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("坏行\n", encoding="utf-8")
    assert EvolutionReportStore(tmp_path).list() == []
