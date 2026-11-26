"""R2.2 手动 smoke：把 R2.1 的候选接进 child/parent 隔离验证。

合成 held-out validation 证据（明确标注 smoke），不写生产档案、不晋升。
三种结果：improved / regression / insufficient。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.evidence import EvidenceStore, ExecutionEvidence, SAMPLE_VALIDATION
from yoai.evolution import CandidateValidator, EvolutionArchive, EvolutionReportStore, R3Promoter

# 每个候选的 child/parent 成功数（共 8 条验证样本/节点）
OUTCOMES = {
    "temporal": (7, 3),          # improved
    "multi-session": (2, 6),     # regression
    "knowledge-update": (5, 5),  # insufficient / no_regression
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(ROOT / "bench_results" / "rsi-trigger-smoke"))
    args = ap.parse_args()
    source = Path(args.source)

    ev_store = EvidenceStore(source / "evidence.json")
    reports = EvolutionReportStore(source)
    archive = EvolutionArchive(source / "evolution" / "evolution.json")

    results = []
    for node in archive.list_nodes():
        if node.lifecycle != "candidate":
            continue
        tag = str(node.diff.get("tag", ""))
        parent = archive.get(node.parent_id or "")
        if not tag or parent is None:
            continue
        child_ok, parent_ok = OUTCOMES.get(tag, (5, 5))
        validation_items = ev_store.query(sample_class=SAMPLE_VALIDATION)
        existing_child = [e for e in validation_items
                          if e.expert_id == node.id and tag in e.fingerprint_tags]
        existing_parent = [e for e in validation_items
                           if e.expert_id == parent.id and tag in e.fingerprint_tags]
        for role, already, expert_id, parent_id, ok_count in (
            ("child", existing_child, node.id, parent.id, child_ok),
            ("parent", existing_parent, parent.id, parent.parent_id or "", parent_ok),
        ):
            if not already:
                for i in range(8):
                    ok = i < ok_count
                    ev_store.add(ExecutionEvidence.create(
                        session_id=f"smoke-val-{tag}",
                        task=f"{tag} validation {role} {i}",
                        task_fingerprint=f"val-{tag}-{role}-{i}",
                        fingerprint_tags=(tag,), sample_class=SAMPLE_VALIDATION,
                        expert_id=expert_id, parent_id=parent_id,
                        status="ok" if ok else "error",
                        verification={"status": "verified_success" if ok else "verified_failure"},
                        tool_calls=(), usage={"total_tokens": 500},
                    ))

        validator = CandidateValidator(archive, ev_store, reports)
        validation = validator.validate(node.id)
        promotion = R3Promoter(archive, ev_store, reports).apply(validation)
        current = archive.get(node.id)
        results.append({**validation.to_dict(), "promotion": promotion.to_dict(),
                        "lifecycle": current.lifecycle if current else ""})
        print(f"[validate] {tag}: {validation.verdict} "
              f"child={validation.child_validation} parent={validation.parent_validation} "
              f"→ {current.lifecycle if current else '?'} ({promotion.reason})")

    summary = {
        "kind": "synthetic_smoke_not_production",
        "source": str(source),
        "results": results,
        "lifecycle_unchanged": False,
        "note": "R3.1 smoke：improved→probation, regression→retired, 其余保持 candidate",
    }
    (source / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[smoke] summary={source / 'validation_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
