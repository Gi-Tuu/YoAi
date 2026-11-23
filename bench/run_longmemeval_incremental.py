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
# Core 源码根目录：环境变量优先，否则从 PYTHONPATH 已注入的路径复用
if not any((Path(p) / "yai_core").is_dir() for p in sys.path if p):
    import os
    _core = os.environ.get("YAI_CORE_SRC")
    if _core and (Path(_core) / "src" / "yai_core").is_dir():
        sys.path.insert(0, str(Path(_core) / "src"))
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


async def _write_one_turn(
    turn: dict, i: int, out_dir: Path, tmem: TemporalMemory,
    temperature: float, max_chars: int,
) -> int:
    """处理单条消息：一次模型调用，模型只看到这一条。返回工具调用次数。"""
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
    # write_calls 口径 = 每 turn 一次模型调用轮次（与原版 total_calls += 1 一致）；
    # triggered 才看 tool_call 事件数。两者不同，别混。
    n_events = 0
    async for event in agent.astream(TURN_PROMPT.format(msg=msg)):
        if event.type == EventType.TOOL_CALL:
            n_events += 1
    return n_events


def _merge_events(src: TemporalMemory, dst: TemporalMemory) -> None:
    """把 src 的事件按 _events 原顺序 append 到 dst（保序合并，保留 event_time 等字段）。"""
    for ev in src._events:
        dst._events.append(dict(ev))
    dst._save()


async def _write_incremental(
    case: dict, tmem: TemporalMemory, out_dir: Path, temperature: float = 0.1,
    max_chars: int = 0, concurrency: int = 8,
) -> tuple[int, int, int]:
    """逐条写入：每条消息一次模型调用，模型只看到这一条。

    concurrency=1 为原始串行（写入直接进 tmem）；>1 为 L1 并发：
    每条用独立影子 tmem 抽取，全部完成后按原顺序合并进主 tmem——
    模型输入/抽取结果与串行版逐字一致，写入顺序也一致（等价）。
    """
    turns = _flat_turns(case)
    if concurrency <= 1:
        calls_list: list[int] = []
        for i, turn in enumerate(turns):
            calls_list.append(await _write_one_turn(turn, i, out_dir, tmem, temperature, max_chars))
    else:
        # 影子 tmem：每条独立，避免并发写竞争；path 放各自 turn 目录
        shadow = [TemporalMemory(out_dir / f"turn_{i}" / "shadow.json") for i in range(len(turns))]
        for s in shadow:
            s._events = []   # 确保干净起点（路径可能复用）
        calls_list = await asyncio.gather(*[
            _write_one_turn(turn, i, out_dir, shadow[i], temperature, max_chars)
            for i, turn in enumerate(turns)
        ])
        # 按原顺序合并进主 tmem（保序）
        for s in shadow:
            _merge_events(s, tmem)
    # write_calls 与原版口径一致 = turn 总数（每 turn 一次模型调用轮次）；
    # triggered = 有工具调用的 turn 数。
    return tmem.count(), len(turns), sum(1 for c in calls_list if c > 0)


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


async def _answer_one(case: dict, out_dir: Path, temperature: float, max_chars: int = 0,
                      concurrency: int = 8) -> tuple[str, dict]:
    tmem = TemporalMemory(out_dir / "tmem.json")
    written, calls, triggered = await _write_incremental(
        case, tmem, out_dir, temperature, max_chars, concurrency
    )
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
    ap.add_argument("--concurrency", type=int, default=8,
                    help="L1 题内写入并发数(抽取并行+影子tmem按序合并)；1=原串行。"
                         "10题A/B: 9/10 vs 8/10(在±12pp波动内)，提速6.7×")
    ap.add_argument("--case-concurrency", type=int, default=1,
                    help="L2 题目间并发数(题内仍串行，零共享状态)；1=原串行")
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
        "concurrency": args.concurrency,
        "case_concurrency": args.case_concurrency,
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

    # 已完成题先按原顺序填入
    pending: list[tuple[int, dict]] = []
    for i, case in enumerate(sample, 1):
        qid = case["question_id"]
        if qid in done:
            rec = done[qid]
            hyps.append({"question_id": qid, "hypothesis": rec.get("hypothesis", "")})
            traces.append(rec.get("trace", {}))
        else:
            pending.append((i, case))

    file_lock = asyncio.Lock()

    async def run_case(i: int, case: dict, sem: asyncio.Semaphore) -> tuple[int, dict, dict]:
        qid = case["question_id"]
        case_dir = out / f"case_{i}"
        case_dir.mkdir(exist_ok=True)
        async with sem:
            try:
                answer, meta = await _answer_one(
                    case, case_dir, args.temperature, args.max_chars, args.concurrency
                )
            except Exception as exc:
                answer, meta = "", {"error": f"{type(exc).__name__}: {exc}"}
        trace = {
            "question_id": qid, "question_type": case["question_type"],
            "question": case["question"], "answer": str(case["answer"]),
            "hypothesis": answer, **meta,
        }
        async with file_lock:
            with progress.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"question_id": qid, "hypothesis": answer,
                                     "trace": trace}, ensure_ascii=False) + "\n")
                fh.flush()
        print(f"[{i}/{len(sample)}] {qid[:8]} turns={meta.get('n_turns')} "
              f"trig={meta.get('triggered')}/{meta.get('write_calls')} "
              f"mem={meta.get('events_recorded')} -> {answer[:30]!r}", flush=True)
        return i, {"question_id": qid, "hypothesis": answer}, trace

    if args.case_concurrency <= 1:
        # 原串行路径（等价基线）
        for i, case in pending:
            _, h, t = asyncio.run(run_case(i, case, asyncio.Semaphore(1)))
            hyps.append(h); traces.append(t)
    else:
        # L2: 题目间并发，题内仍串行(concurrency=1)；每题零共享状态
        async def main_async() -> None:
            sem = asyncio.Semaphore(args.case_concurrency)
            results = await asyncio.gather(*[run_case(i, c, sem) for i, c in pending])
            # 按 sample 原顺序重组
            order = {i: idx for idx, (i, _) in enumerate(pending)}
            by_i = {i: (h, t) for i, h, t in results}
            # 已完成题 + 新题按原 sample 顺序输出
            new_hyps: list[dict] = []
            new_traces: list[dict] = []
            done_by_qid = {h["question_id"]: h for h in hyps}
            done_t_by_qid = {t.get("question_id"): t for t in traces}
            for idx, case in enumerate(sample, 1):
                qid = case["question_id"]
                if qid in done_by_qid:
                    new_hyps.append(done_by_qid[qid]); new_traces.append(done_t_by_qid[qid])
                else:
                    # 找到该题对应的 i
                    for i2, c2 in pending:
                        if c2["question_id"] == qid:
                            h, t = by_i[i2]
                            new_hyps.append(h); new_traces.append(t)
                            break
            hyps.clear(); traces.clear()
            hyps.extend(new_hyps); traces.extend(new_traces)
        asyncio.run(main_async())

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
