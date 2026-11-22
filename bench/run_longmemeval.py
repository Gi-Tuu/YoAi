"""LongMemEval 最小评测适配器（独立 bench/，不改 src/yoai 执行逻辑）。

流程：oracle 数据集 → 每题灌历史到 Core memory → YoAiAgent.astream 答题
     → 收集 DONE.final_text → 写官方 jsonl（question_id + hypothesis）
     → 交给官方评分脚本（复制版，judge 换 deepseek，prompt 原样）。

时间信息处理：oracle 集每条 haystack session 有日期（haystack_dates），
把日期作为文本前缀注入消息 content，让时间推理题可答。这是输入适配，不改评分。

用法：
  python bench/run_longmemeval.py --limit 60 --out bench_results/run1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:\Competition\YAI Agent Core") / "src"))

from yai_core import EventType  # noqa: E402
from yai_core.memory import SqliteStore  # noqa: E402
from yai_core.types import ChatMessage  # noqa: E402

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.models import GatewayModelProvider, SuanliAdapter  # noqa: E402


def _layered_sample(cases: list[dict], limit: int, seed: int) -> list[dict]:
    """按 question_type 分层抽样，覆盖全部题型。"""
    rng = random.Random(seed)
    # limit >= 总数：直接跑全量（打乱顺序即可），避免分层轮流取时某类抽空导致漏题
    if limit >= len(cases):
        full = list(cases)
        rng.shuffle(full)
        return full
    by_type: dict[str, list[dict]] = {}
    for c in cases:
        by_type.setdefault(c["question_type"], []).append(c)
    picked: list[dict] = []
    seen: set[str] = set()
    types = sorted(by_type)
    # 无放回：每类按 seed 洗牌后轮流取，抽完该类就跳过，避免同一题重复计入
    shuffled = {t: rng.sample(v, len(v)) for t, v in by_type.items()}
    cursors = {t: 0 for t in types}
    for i in range(limit):
        t = types[i % len(types)]
        bucket = shuffled[t]
        while cursors[t] < len(bucket) and bucket[cursors[t]]["question_id"] in seen:
            cursors[t] += 1
        if cursors[t] >= len(bucket):
            continue
        case = bucket[cursors[t]]
        cursors[t] += 1
        seen.add(case["question_id"])
        picked.append(case)
    rng.shuffle(picked)
    return picked


async def _answer(case: dict, tmp_db: Path, model_factory) -> tuple[str, dict]:
    """单题：灌历史 → 答题 → 返回 (hypothesis, 执行元数据)。"""
    store = SqliteStore(tmp_db)
    dates = case.get("haystack_dates") or []
    sessions = case.get("haystack_sessions") or []
    # 灌历史：每条消息带 session 日期前缀（保留时间推理线索）
    for idx, session in enumerate(sessions):
        date = str(dates[idx]) if idx < len(dates) else ""
        for turn in session:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", ""))
            content = str(turn.get("content", ""))
            if role not in ("user", "assistant"):
                continue
            prefix = f"[日期：{date}] " if date else ""
            await store.append_history(
                ChatMessage(role=role, content=prefix + content)
            )

    agent = YoAiAgent(model=model_factory(), data_dir=tmp_db.parent / "ctx", memory=store)
    # 纯记忆 QA：清空工具注册表 → router 硬规则强制 direct，模型不会误报工具调用
    from yai_core.tools import ToolRegistry
    agent.core.registry = ToolRegistry()
    final = ""
    events = 0
    verification = None
    # 时间锚点：LongMemEval 的"三周前/两个月前的周三"以 question_date 为"现在"。
    # 原适配器只把 haystack_dates 注入历史，question_date 从未传给模型 →
    # 模型只能答"0 周前"。这是评测输入适配缺失，必须补。
    question = case["question"]
    qdate = str(case.get("question_date") or "").strip()
    if qdate:
        question = f"[当前日期：{qdate}]\n{question}"
    async for event in agent.astream(question):
        events += 1
        if event.type == EventType.DONE:
            final = str(event.data.get("final_text") or "")
            verification = event.data.get("verification")
    meta = {
        "events": events,
        "verification": verification.get("status") if verification else None,
        "usage": getattr(agent.model, "total_usage", {}),
    }
    if hasattr(store, "close"):
        store.close()
    return final.strip(), meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "bench_data" / "longmemeval_oracle.json"))
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--type", default="", help="只跑某一 question_type（如 temporal-reasoning）")
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--out", default=str(ROOT / "bench_results" / "lme-oracle-run1"))
    args = ap.parse_args()

    cases = json.load(open(args.data, encoding="utf-8"))
    if args.type:
        cases = [c for c in cases if c.get("question_type") == args.type]
    sample = _layered_sample(cases, args.limit, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 配置快照
    config = {
        "benchmark": "LongMemEval",
        "split": "oracle",
        "data_file": str(args.data),
        "data_sha256": __import__("hashlib").sha256(Path(args.data).read_bytes()).hexdigest(),
        "n_questions": len(sample),
        "seed": args.seed,
        "sampling": "layered by question_type, seed",
        "answer_model": "deepseek/deepseek-v4.1-flash-1017 (suanli.cn, free)",
        "answer_adapter": "bench.bench_model.BenchModelProvider (no tools; reasoning_content fallback)",
        "history_injection": "haystack_sessions -> Core SqliteStore history, date prefix per session",
        "judge": "see score step (official anscheck prompt preserved)",
    }
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    hypotheses: list[dict] = []
    traces: list[dict] = []
    for i, case in enumerate(sample, 1):
        tmp_db = out / f"_tmp_{i}.db"
        try:
            from bench.bench_model import BenchModelProvider
            answer, meta = asyncio.run(_answer(case, tmp_db, BenchModelProvider))
        except Exception as exc:  # 单题失败不中断整轮，如实记录
            answer, meta = "", {"error": f"{type(exc).__name__}: {exc}"}
        hypotheses.append({"question_id": case["question_id"], "hypothesis": answer})
        traces.append({
            "question_id": case["question_id"],
            "question_type": case["question_type"],
            "question": case["question"],
            "answer": case["answer"],
            "hypothesis": answer,
            **meta,
        })
        print(f"[{i}/{len(sample)}] {case['question_id']} -> {answer[:60]!r}", flush=True)
        tmp_db.unlink(missing_ok=True)

    (out / "hypotheses.jsonl").write_text(
        "\n".join(json.dumps(h, ensure_ascii=False) for h in hypotheses), encoding="utf-8"
    )
    (out / "traces.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in traces), encoding="utf-8"
    )
    print(f"WROTE {out / 'hypotheses.jsonl'} ({len(hypotheses)} predictions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
