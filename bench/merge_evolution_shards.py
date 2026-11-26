"""合并进化 A/B/C/D 的分片结果。

- traces.jsonl 全量保留（含 parent 变体，供 BenchmarkLab 审计）；
- hypotheses.jsonl 只取 child 变体（或无 variant 的旧格式），每组每题一条，供判分。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    shards = Path(args.shards)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for group in ("A", "B", "C", "D"):
        traces: list[dict] = []
        for shard in sorted(shards.glob(f"{group}*/{group}/traces.jsonl")):
            for line in shard.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    traces.append(json.loads(line))
        child = [t for t in traces if t.get("variant", "child") == "child"]
        (out / group).mkdir(parents=True, exist_ok=True)
        (out / group / "traces.jsonl").write_text(
            "\n".join(json.dumps(t, ensure_ascii=False) for t in traces), encoding="utf-8")
        (out / group / "hypotheses.jsonl").write_text(
            "\n".join(json.dumps({"question_id": t["question_id"],
                                  "hypothesis": t.get("hypothesis", "")},
                                 ensure_ascii=False) for t in child), encoding="utf-8")
        print(f"{group}: traces={len(traces)} scored={len(child)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
