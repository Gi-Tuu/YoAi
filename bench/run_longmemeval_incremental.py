"""LongMemEval 单轮递增写入评测（贴近生产口径）。

与 run_longmemeval_retrieval.py 的唯一差异在**写入阶段**：
- 批量版：haystack 一次性喂入，一次模型调用批量抽取（生产不存在此场景）
- 本版：haystack 逐条喂入，每条一次模型调用逐条写入（= 生产真实对话形态）

答题阶段逐字复用批量版（question_date 锚点 + 工具检索 prompt + 关联工具），
保证两者差异只在"写入方式"。

用法：
  python bench/run_longmemeval_incremental.py --limit 30 --out bench_results/lme-inc-30
  python bench/run_longmemeval_incremental.py --limit 500 --out bench_results/lme-inc-500
评分：
  python bench/score_longmemeval.py --hyp <out>/hypotheses.jsonl --out <out>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:\Competition\YAI Agent Core") / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from yai_core import EventType  # noqa: E402
from yai_core.tools import ToolRegistry  # noqa: E402

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.models import GatewayModelProvider, SuanliAdapter  # noqa: E402
from yoai.temporal_memory import TemporalMemory  # noqa: E402
from run_longmemeval_retrieval import _iso_date, _topics  # noqa: E402

# 单轮抽取 prompt（已验证触发率 10/10，见 SINGLE-TURN-MEMORY-FEASIBILITY.md）
TURN_PROMPT = (
    "请从下面这条消息中提取事实，用 remember_event 工具逐条记下来"
    "（数字、名字、时间、地点、偏好、所有物、明确结论）。"
    "用户说的 speaker 填 user，助手给出的具体结论 speaker 填 assistant，"
    "每条给 event_time 和 topics。不要记寒暄。记完回复你记了几条。\n\n消息：\n{msg}"
)


def _sample(cases: list[dict], limit: int, seed: int) -> list[dict]:
    out = list(cases)
    random.Random(seed).shuffle(out)
    return out[:limit]


def _flat_turns(case: dict) -> list[dict[str, str]]:
    """把 haystack 展平成按时间顺序的逐条消息（含 role 与日期）。"""
    dates = case.get("haystack_dates") or []
    turns: list[dict[str, str]] = []
    for idx, session in enumerate(case.get("haystack_sessions") or []):
        date = _iso_date(str(dates[idx]) if idx < len(dates) else "")
        for turn in session:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", ""))
            content = str(turn.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                turns.append({"role": role, "content": content, "date": date})
    return turns


async def _write_incremental(
    case: dict, tmem: TemporalMemory, out_dir: Path, temperature: float = 0.1,
    max_chars: int = 0,
) -> tuple[int, int, int]:
    """逐条写入：每条消息一次模型调用，模型只看到这一条。返回(写入条数, 调用次数, 触发条数)。"""
    turns = _flat_turns(case)
    total_written = 0
    total_calls = 0
    triggered = 0
    for i, turn in enumerate(turns):
        turn_dir = out_dir / f"turn_{i}"
        turn_dir.mkdir(parents=True, exist_ok=True)
        adapter = SuanliAdapter(temperature=temperature)
        agent = YoAiAgent(
            model=GatewayModelProvider(adapter), data_dir=turn_dir / "ctx",
            temporal_memory=tmem,
        )
        # 只暴露 remember_event（评测写入阶段惯例，避免模型改用别的工具）
        only = ToolRegistry()
        for s in agent.core.registry.all():
            if getattr(s, "name", "") == "remember_event":
                only.register(s)
        agent.core.registry = only

        # 输入带日期前缀，让模型给 event_time
        # max_chars<=0 表示不截断（修复助手长列表后半段答案被砍掉的 bug）
        content = turn['content'] if max_chars <= 0 else turn['content'][:max_chars]
        msg = f"[{turn['date']}] {turn['role']}: {content}"
        calls = 0
        async for event in agent.astream(TURN_PROMPT.format(msg=msg)):
            if event.type == EventType.TOOL_CALL:
                calls += 1
        total_calls += 1
        if calls > 0:
            triggered += 1
        total_written = tmem.count()
    return total_written, total_calls, triggered


async def _answer(case: dict, out_dir: Path, tmem: TemporalMemory) -> tuple[str, dict]:
    """答题阶段：与批量版逐字一致（question_date 锚点 + 工具检索 prompt）。"""
    adapter = SuanliAdapter()   # 答题用默认温度（生产一致）
    agent = YoAiAgent(
        model=GatewayModelProvider(adapter), data_dir=out_dir / "answer_ctx",
        temporal_memory=tmem,
    )
    question = case["question"]
    qdate = _iso_date(str(case.get("question_date") or "").strip())
    if qdate:
        question = (
            f"[当前日期：{qdate}]\n{question}\n\n"
            "请用记忆工具检索后回答。汇总类问题（总共几件/多少钱/多少次）"
            "务必先用 all_topics 发现主题，再用 summarize_theme 取该主题下全部事件，"
            "不要只凭一条记忆下结论。若问的是你之前提到的资源/公司/数字，"
            "用 related_events 按关键词检索，注意 speaker=assistant 的记忆。"
        )
    final = ""
    tool_calls: list[str] = []
    async for event in agent.astream(question):
        if event.type == EventType.TOOL_CALL:
            tool_calls.append(str(event.data.get("tool", "")))
        if event.type == EventType.DONE:
            final = str(event.data.get("final_text") or "")
    return final.strip(), {"tool_calls": tool_calls}


async def _answer_one(case: dict, out_dir: Path, temperature: float, max_chars: int = 0) -> tuple[str, dict]:
    tmem = TemporalMemory(out_dir / "tmem.json")
    written, calls, triggered = await _write_incremental(case, tmem, out_dir, temperature, max_chars)
    answer, answer_meta = await _answer(case, out_dir, tmem)
    return answer, {
        "events_recorded": written, "write_calls": calls, "triggered": triggered,
        "n_turns": len(_flat_turns(case)), "memory_source": "incremental",
        **answer_meta,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "bench_data" / "longmemeval_oracle.json"))
    ap.add_argument("--type", default="")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--temperature", type=float, default=0.1,
                    help="单轮写入温度（单轮场景默认/0.1无差别，保持0.1）")
    ap.add_argument("--max-chars", type=int, default=0,
                    help="写入时每条消息截断长度；默认0=不截断（600是旧bug值，"
                         "会砍掉助手长列表后半段答案：A/B 66.7%%→96.7%%, p=0.0039）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cases = json.load(open(args.data, encoding="utf-8"))
    if args.type:
        cases = [c for c in cases if c["question_type"] == args.type]
    sample = _sample(cases, args.limit, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    config = {
        "benchmark": "LongMemEval", "mode": "incremental single-turn write (贴近生产)",
        "split": "oracle", "question_type": args.type, "n": len(sample), "seed": args.seed,
        "answer_model": "deepseek/deepseek-v4.1-flash-1017 (suanli.cn, free)",
        "write_temperature": args.temperature,
        "max_chars": args.max_chars,
        "write": "each haystack turn -> one model call -> remember_event (逐条递增)",
        "answer": "same as batch version (question_date + tool retrieval)",
        "note": "写入阶段逐条(生产形态)，答题阶段与批量版逐字一致",
    }
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    progress = out / "progress.jsonl"
    done: dict[str, dict] = {}
    if progress.exists():
        for line in progress.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    done[rec["question_id"]] = rec
                except (json.JSONDecodeError, KeyError):
                    pass
    print(f"RESUME {len(done)}/{len(sample)}", flush=True)

    hyps: list[dict] = []
    traces: list[dict] = []
    for i, case in enumerate(sample, 1):
        qid = case["question_id"]
        if qid in done:
            rec = done[qid]
            hyps.append({"question_id": qid, "hypothesis": rec.get("hypothesis", "")})
            traces.append(rec.get("trace", {}))
            continue
        case_dir = out / f"case_{i}"
        case_dir.mkdir(exist_ok=True)
        try:
            answer, meta = asyncio.run(_answer_one(case, case_dir, args.temperature, args.max_chars))
        except Exception as exc:
            answer, meta = "", {"error": f"{type(exc).__name__}: {exc}"}
        trace = {
            "question_id": qid, "question_type": case["question_type"],
            "question": case["question"], "answer": str(case["answer"]),
            "hypothesis": answer, **meta,
        }
        hyps.append({"question_id": qid, "hypothesis": answer})
        traces.append(trace)
        with progress.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"question_id": qid, "hypothesis": answer,
                                 "trace": trace}, ensure_ascii=False) + "\n")
            fh.flush()
        print(f"[{i}/{len(sample)}] {qid[:8]} turns={meta.get('n_turns')} "
              f"trig={meta.get('triggered')}/{meta.get('write_calls')} "
              f"mem={meta.get('events_recorded')} -> {answer[:30]!r}", flush=True)

    (out / "hypotheses.jsonl").write_text(
        "\n".join(json.dumps(h, ensure_ascii=False) for h in hyps), encoding="utf-8"
    )
    (out / "traces.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in traces), encoding="utf-8"
    )
    print(f"WROTE {out/'hypotheses.jsonl'} ({len(hyps)})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
