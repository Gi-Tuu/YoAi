"""R2.1 手动 smoke：跑一批候选看看（合成样本，不写生产档案）。

用途：真实边界样本不够时，用三条典型场景验证触发引擎的候选质量：
1. temporal / 能力归因 → 候选补工具
2. multi-session / 路由归因 → 候选补能力标签
3. knowledge-update / 能力归因但无新工具 → 候选补提示

所有数据写入 --out 指定的独立目录，绝不碰 dist/output 或用户数据。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.evidence import (
    Attribution,
    EvidenceStore,
    ExecutionEvidence,
    FeedbackSignal,
    FeedbackStore,
    build_boundary_report,
)
from yoai.evolution import EvolutionArchive, EvolutionReportStore, ExpertSpec, TriggerEngine


SCENARIOS = [
    {"tag": "temporal", "cause": "capability", "success": 12, "rework": 5,
     "tools": ("events_between", "facts_by_tag")},
    {"tag": "multi-session", "cause": "routing", "success": 12, "rework": 6,
     "tools": ("all_topics",)},
    {"tag": "knowledge-update", "cause": "capability", "success": 12, "rework": 5,
     "tools": ()},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1]
                                        / "bench_results" / "rsi-trigger-smoke"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ev_store = EvidenceStore(out / "evidence.json")
    fb_store = FeedbackStore(out)
    ar = EvolutionArchive(out / "evolution" / "evolution.json")
    reports = EvolutionReportStore(out)
    root = ar.create_root("root", ExpertSpec(
        tools=("list_facts", "recall_fact"), capability_tags=("root",),
        prompt_suffix="通用助手",
    ))

    for scenario in SCENARIOS:
        tag = scenario["tag"]
        for i in range(20):
            ok = i < scenario["success"]
            evidence = ExecutionEvidence.create(
                session_id=f"smoke-{tag}", task=f"{tag} 任务{i}",
                task_fingerprint=f"{tag}-{i}", fingerprint_tags=(tag,),
                expert_id=root.id,
                status="ok" if ok else "error",
                verification={"status": "verified_success" if ok else "verified_failure"},
                tool_calls=scenario["tools"], usage={"total_tokens": 1000},
            )
            ev_store.add(evidence)
            ev_store.add_attribution(Attribution(
                evidence_id=evidence.id, cause=scenario["cause"],
                confidence=0.85, reason=f"smoke {tag} {scenario['cause']}",
            ))
            if i < scenario["rework"]:
                fb_store.add(FeedbackSignal(
                    id=f"f-{tag}-{i}", evidence_id=evidence.id,
                    run_id=f"r-{tag}-{i}", session_id=f"smoke-{tag}",
                    kind="regenerate", polarity=-1,
                    task_fingerprint=evidence.task_fingerprint,
                    fingerprint_tags=(tag,), note="smoke 负向反馈",
                ))

    report = build_boundary_report(ev_store, fb_store)
    engine = TriggerEngine(ar, ev_store, reports)
    decisions = [d.to_dict() for d in engine.evaluate(report)]

    candidates = []
    for decision in decisions:
        node = ar.get(decision["node_id"]) if decision["node_id"] else None
        candidates.append({
            **decision,
            "lifecycle": node.lifecycle if node else "",
            "spec": node.spec.to_dict() if node else {},
            "diff": node.diff if node else {},
        })

    summary = {
        "kind": "synthetic_smoke_not_production",
        "out": str(out),
        "boundary": report.to_dict(),
        "decisions": decisions,
        "candidates": candidates,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[smoke] boundary rows: {len(report.rows)}")
    for item in candidates:
        if not item["created"]:
            print(f"[skip] {item['tag']}: {item['reason']}")
            continue
        diff = item["diff"]
        print(f"[candidate] {item['tag']} node={item['node_id']} "
              f"dimension={diff.get('dimension')} lifecycle={item['lifecycle']}")
        print(f"           {item['reason']}")
        print(f"           tools={item['spec']['tools']} tags={item['spec']['capability_tags']}")
    print(f"[smoke] archive={out / 'evolution' / 'evolution.json'}")
    print(f"[smoke] reports={out / 'evolution' / 'reports.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
