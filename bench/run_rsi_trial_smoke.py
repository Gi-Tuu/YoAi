"""R3.2 手动 smoke：对 probation 候选跑成对试用并走人工批准。

合成 trial 证据，不写生产档案；产物写入 rsi-trigger-smoke 目录。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.evidence import (
    EvidenceStore, ExecutionEvidence, FeedbackSignal, FeedbackStore, SAMPLE_TRIAL,
)
from yoai.evolution import (
    EvolutionArchive, EvolutionReportStore, TrialController, TrialStore,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(ROOT / "bench_results" / "rsi-trigger-smoke"))
    args = ap.parse_args()
    source = Path(args.source)

    ev_store = EvidenceStore(source / "evidence.json")
    fb_store = FeedbackStore(source)
    reports = EvolutionReportStore(source)
    trials = TrialStore(source)
    archive = EvolutionArchive(source / "evolution" / "evolution.json")
    controller = TrialController(archive, ev_store, fb_store, reports, trials)

    probation = [n for n in archive.list_nodes() if n.lifecycle == "probation"
                 and n.diff.get("tag") == "temporal"]
    if not probation:
        print("[smoke] 没有 temporal probation 候选，请先跑 R3.1 smoke")
        return 1
    node = probation[0]
    parent = archive.get(node.parent_id or "")
    if parent is None:
        print("[smoke] 父节点不存在")
        return 1

    for old in trials.list(node_id=node.id, status="running"):
        controller.stop(old.id, "smoke 重置")
    record = controller.start(node.id, "tag:temporal", 20)

    for role, expert_id, ok_count, rework_count in (
        ("child", node.id, 20, 2),
        ("parent", parent.id, 16, 2),
    ):
        for i in range(20):
            ok = i < ok_count
            evidence = ExecutionEvidence.create(
                session_id="smoke-trial", task=f"temporal trial {role} {i}",
                task_fingerprint=f"trial-temporal-{role}-{i}",
                fingerprint_tags=("temporal",), sample_class=SAMPLE_TRIAL,
                expert_id=expert_id, parent_id=parent.id,
                trial_id=record.id, trial_role=role,
                status="ok" if ok else "error",
                verification={"status": "verified_success" if ok else "verified_failure"},
                usage={"total_tokens": 1000},
            )
            ev_store.add(evidence)
            if i < rework_count:
                fb_store.add(FeedbackSignal(
                    id=f"trial-f-{role}-{i}", evidence_id=evidence.id,
                    run_id=f"trial-r-{role}-{i}", session_id="smoke-trial",
                    kind="regenerate", polarity=-1,
                    task_fingerprint=evidence.task_fingerprint,
                    fingerprint_tags=("temporal",), note="smoke 试用返工",
                ))

    report = controller.report(record.id)
    print(f"[trial] passed={report.passed} reason={report.reason}")
    if not report.passed:
        (source / "trial_smoke_summary.json").write_text(
            json.dumps({"passed": False, "report": report.to_dict()},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    approved = controller.approve(record.id, "smoke-approver", "合成 smoke 人工批准")
    current = archive.get(node.id)
    summary = {
        "kind": "synthetic_smoke_not_production",
        "trial_id": record.id,
        "approved": approved.passed,
        "lifecycle": current.lifecycle if current else "",
        "report": approved.to_dict(),
    }
    (source / "trial_smoke_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[approve] {node.id}: {current.lifecycle if current else '?'}")
    print(f"[smoke] summary={source / 'trial_smoke_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
