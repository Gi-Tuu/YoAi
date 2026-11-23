"""量化模型自记的随机性：同题多次跑记忆阶段，比较条数与内容重合度。

只跑记忆阶段（不答题、不评分），快速。比较 temperature 默认 vs 0.1。
用法：
  python bench/probe_selfmemory_variance.py --temp 0.1 --reps 3 --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Core 源码根目录：环境变量优先，否则从 PYTHONPATH 已注入的路径复用
if not any((Path(p) / "yai_core").is_dir() for p in sys.path if p):
    import os
    _core = os.environ.get("YAI_CORE_SRC")
    if _core and (Path(_core) / "src" / "yai_core").is_dir():
        sys.path.insert(0, str(Path(_core) / "src"))
sys.path.insert(0, str(ROOT))

from yai_core import EventType  # noqa: E402
from yoai.agent import YoAiAgent  # noqa: E402
from yoai.models import GatewayModelProvider, SuanliAdapter  # noqa: E402
from yoai.temporal_memory import TemporalMemory  # noqa: E402

sys.path.insert(0, str(ROOT / "bench"))
from run_longmemeval_retrieval import _iso_date, _topics, _memory_phase_model  # noqa: E402


async def run_memory_once(case: dict, temp: float | None, seed_dir: Path) -> list[str]:
    """复用正式记忆阶段（已验证能触发工具调用），只注入 temperature。"""
    tmem = TemporalMemory(seed_dir / "tmem.json")
    adapter = SuanliAdapter(temperature=temp)
    factory = lambda: GatewayModelProvider(adapter)
    calls, source = await _memory_phase_model(case, tmem, seed_dir, factory)
    return [e["what"] for e in tmem.timeline()]


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(x.strip().lower()[:60] for x in a), set(x.strip().lower()[:60] for x in b)
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temp", type=float, default=None)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--out", default="output/probe-variance")
    args = ap.parse_args()

    cases = json.load(open(ROOT / "bench_data" / "longmemeval_oracle.json", encoding="utf-8"))
    cases = cases[:args.limit]
    out = ROOT / args.out / ("default" if args.temp is None else f"t{args.temp}")
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for ci, case in enumerate(cases, 1):
        runs = []
        for r in range(args.reps):
            facts = await run_memory_once(case, args.temp, out / f"q{ci}_r{r}")
            runs.append(facts)
        counts = [len(f) for f in runs]
        sims = [jaccard(runs[0], f) for f in runs[1:]] or [1.0]
        results.append({
            "qid": case["question_id"], "counts": counts,
            "mean_count": sum(counts) / len(counts),
            "jaccard_vs_first": sims,
            "mean_jaccard": sum(sims) / len(sims),
        })
        print(f"[{ci}/{len(cases)}] {case['question_id'][:8]} counts={counts} "
              f"mean_jaccard={sum(sims)/len(sims):.2f}", flush=True)

    summary = {
        "temperature": args.temp, "reps": args.reps, "n_questions": len(cases),
        "mean_count_std": (
            sum((r["mean_count"] - sum(x["mean_count"] for x in results) / len(results)) ** 2
                for r in results) / len(results)
        ) ** 0.5,
        "overall_mean_jaccard": sum(r["mean_jaccard"] for r in results) / len(results),
        "details": results,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"=== temp={args.temp} overall_mean_jaccard={summary['overall_mean_jaccard']:.3f} "
          f"mean_count_std={summary['mean_count_std']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
