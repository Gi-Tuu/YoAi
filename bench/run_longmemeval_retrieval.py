"""LongMemEval retrieval 模式评测适配器（测 YoAi 记忆层，而非长上下文）。

与 run_longmemeval.py（oracle 长上下文 QA）的区别：
- oracle：把整个 haystack 一次性喂进 Core history，模型直接读——**不调用 YoAi 记忆层**。
- retrieval（本文件）：把 haystack 的每个 turn 逐条喂给 YoAi，让它用 remember_event 记住
  （带 event_time），答题时让它用 events_between / facts_by_tag 检索——**真正测记忆层**。

为控制成本，记忆阶段用确定性脚本调用工具（不逐 turn 调模型），答题阶段用真模型 +
工具循环（模型自己决定查哪些工具）。这样测的是"记忆索引是否让检索式答题变准"。

用法：
  python bench/run_longmemeval_retrieval.py --type temporal-reasoning --limit 30 \
      --out bench_results/retrieval-temporal-30
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


def _sample(cases: list[dict], limit: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = list(cases)
    rng.shuffle(out)
    return out[:limit]


def _iso_date(raw: str) -> str:
    """把 LongMemEval 的 '2023/02/14 (Tue) 12:45' 规范成 ISO '2023-02-14T12:45:00'。

    TemporalMemory.events_between 用字符串比较 ISO 时间戳；斜杠格式与模型传的
    横杠 ISO 不匹配，会查不到（retrieval 冒烟暴露的问题）。
    """
    import re
    raw = str(raw or "").strip()
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})\s*(?:\(\w+\))?\s*(\d{2}:\d{2})?", raw)
    if not m:
        return raw
    y, mo, d, hm = m.groups()
    return f"{y}-{mo}-{d}T{hm or '00:00'}:00"


def _fact_text(content: str) -> str:
    """截取用户话里的事实陈述部分，去掉'Can you recommend...'类请求噪音。"""
    text = str(content).strip()
    # 第一个问号前通常是事实陈述；问句整段保留会稀释检索信号
    q = text.find("?")
    if q > 40:
        text = text[:q].strip()
    return text[:400]


# 主题词典：从用户话里识别细粒度主题，供关联索引聚合（multi-session 的关键）
_TOPIC_WORDS = {
    "jewelry": ["jewelry", "necklace", "earring", "ring", "bracelet", "chains"],
    "camping": ["camp", "camping", "hiking", "tent", "outdoor"],
    "travel": ["trip", "travel", "vacation", "flight", "hotel"],
    "money": ["$", "earn", "spend", "sold", "sale", "price", "cost", "budget"],
    "health": ["health", "doctor", "medication", "device", "symptom", "nebulizer"],
    "family": ["sister", "brother", "sibling", "mother", "father", "parent", "cousin"],
    "pets": ["dog", "cat", "pet", "puppy", "kitten"],
    "food": ["recipe", "cook", "restaurant", "grocery", "dinner", "coffee"],
}


def _topics(text: str) -> list[str]:
    low = text.lower()
    return [name for name, words in _TOPIC_WORDS.items() if any(w in low for w in words)]


async def _memory_phase_model(
    case: dict, tmem: TemporalMemory, out_dir: Path, model_factory,
    staged: bool = False, prompt_style: str = "basic",
) -> tuple[int, str]:
    """让模型自己读整段对话、自己决定记哪些事实（真实产品路径验证）。

    staged=True：分两次独立调用，第一次只记用户事实、第二次只记助手结论。
    目的：避开"一次记两类"时模型提取预算被分摊、用户关键数字被漏掉的问题。
    返回 (记录条数, 来源)。
    """
    dates = case.get("haystack_dates") or []
    sessions = case.get("haystack_sessions") or []
    lines: list[str] = []
    lines_user: list[str] = []
    lines_asst: list[str] = []
    for idx, session in enumerate(sessions):
        date = _iso_date(str(dates[idx]) if idx < len(dates) else "")
        for turn in session:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", ""))
            content = str(turn.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                line = f"[{date}] {role}: {content[:300]}"
                lines.append(line)
                # 输入隔离：staged 的两个阶段各看各的话，避免对方的文本占用提取注意力
                if role == "user":
                    lines_user.append(f"[{date}] {content[:300]}")
                else:
                    lines_asst.append(f"[{date}] {content[:300]}")
    transcript = "\n".join(lines)[:12000]
    transcript_user = "\n".join(lines_user)[:12000]
    transcript_asst = "\n".join(lines_asst)[:12000]

    def build_agent(tag: str):
        a = YoAiAgent(
            model=model_factory(), data_dir=out_dir / f"mem_ctx_{tag}", temporal_memory=tmem
        )
        # 记忆写入阶段只暴露 remember_event：模型常擅自改用 remember_fact 致记忆为空
        from yai_core.tools import ToolRegistry
        only = ToolRegistry()
        for s in a.core.registry.all():
            if getattr(s, "name", "") == "remember_event":
                only.register(s)
        a.core.registry = only
        return a

    def fallback(speakers: set[str]) -> int:
        """确定性兜底：只记指定 speaker 的事实，避免模型 0 调用导致该类记忆为空。"""
        turns: list[dict[str, str]] = []
        dates_flat: list[str] = []
        for idx, session in enumerate(sessions):
            date = _iso_date(str(dates[idx]) if idx < len(dates) else "")
            for turn in session:
                if not isinstance(turn, dict):
                    continue
                role = str(turn.get("role", ""))
                if role not in speakers:
                    continue
                turns.append({"role": role, "content": str(turn.get("content", ""))})
                dates_flat.append(date)
        return tmem.remember_from_transcript(
            turns, event_dates=dates_flat, topic_extractor=_topics,
            include_assistant=("assistant" in speakers),
        )

    async def one_pass(prompt: str, tag: str, fb_speakers: set[str]) -> int:
        agent = build_agent(tag)
        calls = 0
        async for event in agent.astream(prompt):
            if event.type == EventType.TOOL_CALL and event.data.get("tool") == "remember_event":
                calls += 1
        if calls == 0:
            calls = fallback(fb_speakers)
        return calls

    if staged:
        # 分段式：两次独立调用，每次目标单一，避免提取预算被挤占
        user_prompt = (
            "下面是用户说过的话（按时间排列）。请用 remember_event 工具，"
            "**把用户提到的事实**逐条记下来（买了什么、去了哪里、花了多少钱、"
            "有几件物品、偏好等）。speaker 一律填 user。"
            "每条给 event_time（行首日期）和 topics（细粒度主题）。"
            "记完回复你记了几条。\n\n" + transcript_user
        )
        asst_prompt = (
            "下面是助手说过的话（按时间排列）。请用 remember_event 工具，"
            "**把助手给出的具体结论**逐条记下来（提到的公司/产品/资源名称、"
            "数字金额、百分比、研究结果等）。speaker 一律填 assistant，"
            "不要记泛泛的建议或客套话。"
            "每条给 event_time（行首日期）和 topics。记完回复你记了几条。\n\n" + transcript_asst
        )
        n_user = await one_pass(user_prompt, "user", {"user"})
        n_asst = await one_pass(asst_prompt, "asst", {"assistant"})
        return n_user + n_asst, "staged"

    # 混合式（v2）：一次记两类
    if prompt_style == "enhanced":
        # 借鉴 AMBRACE EXTRACT_PROMPT 的结构（分类清单+重要度+逐字依据+时间具体化），
        # 针对 LongMemEval 英文 QA 改编。核心：数字/数量单列一类、逐条穷举不合并、
        # 逐字保留数字不脑补——直击"只记11-12条、关键数字漏记"的瓶颈。
        prompt = (
            "Below is a conversation history. Use the remember_event tool to record facts "
            "one by one. Be EXHAUSTIVE — record every distinct fact; do not merge or skip.\n\n"
            "Record these categories:\n"
            "- PEOPLE & RELATIONSHIPS: names, family members, how many siblings/friends, who is who.\n"
            "- NUMBERS & QUANTITIES: prices, amounts, counts, distances, durations, percentages, "
            "ages, dates. **Keep the exact number and unit verbatim** — never round, merge, or omit.\n"
            "- EVENTS & TRIPS: where the user went, what they did, with whom, when.\n"
            "- ITEMS & PURCHASES: what was bought/owned/sold, and how many of each.\n"
            "- PREFERENCES: likes, dislikes, habits.\n"
            "- ASSISTANT CONCLUSIONS: specific resources, company/product names, figures the "
            "assistant stated (speaker=assistant). Skip generic advice.\n\n"
            "CRITICAL — what NOT to record: small talk, acknowledgments, and reactions are NOT facts. "
            "Never record phrases like 'What a fascinating topic', 'Another great question', "
            "'That's helpful', 'You're welcome', 'Good idea', 'Thanks', or any emotional reaction. "
            "Only record concrete, checkable facts (a name, a number, a purchase, a trip, a dated "
            "event, a stated preference). If a line contains no concrete fact, skip it entirely.\n\n"
            "Rules: (1) Each fact on its own remember_event call. (2) Base every fact strictly on "
            "what is literally in the conversation — no guessing. (3) Keep exact numbers verbatim. "
            "(4) Convert relative dates (last week/two months ago) to the concrete date from the "
            "line prefix. (5) For counts like siblings/pets/items, record EACH mention separately "
            "even if they seem redundant. (6) speaker='user' for user facts, 'assistant' for "
            "assistant conclusions. (7) Give event_time (line-prefix date) and topics. "
            "Tell me how many you recorded.\n\n" + transcript
        )
    else:
        prompt = (
            "下面是一段用户与助手的历史对话。请用 remember_event 工具，把对话中的"
            "**关键事实**逐条记下来，包括两类：\n"
            "1. 用户提到的事实（买了什么、去了哪里、花了多少钱、有几件物品、偏好等），speaker 填 user；\n"
            "2. 助手给出的具体结论（提到的公司/产品/资源名称、数字金额、百分比、研究结果等），"
            "speaker 填 assistant。不要记泛泛的建议或客套话。\n"
            "每条给 event_time（对话行首的日期，ISO 格式）和 topics（细粒度主题，"
            "如 jewelry/camping/money）。记完后回复你记了几条。\n\n" + transcript
        )
    calls = await one_pass(prompt, "mixed", {"user", "assistant"})
    source = "model" if calls > 0 else "fallback"
    return calls, source


async def _answer(
    case: dict, out_dir: Path, model_factory, memory_mode: str = "script",
    prompt_style: str = "basic", num_supplement: bool = False,
    entity_supplement: bool = False, memory_model_factory=None,
) -> tuple[str, dict]:
    """memory_model_factory: 仅供记忆阶段用的 model factory（低温抽取实验）；
    缺省 None 时复用 model_factory（答题与记忆同模型）。"""
    if memory_model_factory is None:
        memory_model_factory = model_factory
    """memory_mode: script(确定性) / model(一次记两类) / staged(分两次各记一类)。"""
    """记忆阶段：script 确定性写 或 model 自己记；答题阶段：真模型 + 工具检索。"""
    tmem = TemporalMemory(out_dir / "tmem.json")
    dates = case.get("haystack_dates") or []
    sessions = case.get("haystack_sessions") or []
    recorded = 0
    memory_source = memory_mode
    if memory_mode in ("model", "staged"):
        recorded, memory_source = await _memory_phase_model(
            case, tmem, out_dir, memory_model_factory,
            staged=(memory_mode == "staged"), prompt_style=prompt_style,
        )
    else:
        # script 模式也复用产品层方法，同样抽取用户+助手事实，保证两种模式可比
        turns: list[dict[str, str]] = []
        dates_flat: list[str] = []
        for idx, session in enumerate(sessions):
            date = _iso_date(str(dates[idx]) if idx < len(dates) else "")
            for turn in session:
                if not isinstance(turn, dict):
                    continue
                turns.append({
                    "role": str(turn.get("role", "")),
                    "content": str(turn.get("content", "")),
                })
                dates_flat.append(date)
        recorded = tmem.remember_from_transcript(
            turns, event_dates=dates_flat, topic_extractor=_topics
        )

    # 确定性补充层（借鉴 AMBRACE 正则抽取）：补模型自记漏掉的结构化事实。
    # 数字补充：用户话里"数字+名词"（如 "family with 3 sisters"）；
    # 专名补充：助手话编号列表项（如 "2. Southwest Airlines - ..."，assistant 类答案常在第2+项）。
    num_added = 0
    ent_added = 0
    if num_supplement or entity_supplement:
        all_turns: list[dict[str, str]] = []
        all_dates: list[str] = []
        for idx, session in enumerate(sessions):
            date = _iso_date(str(dates[idx]) if idx < len(dates) else "")
            for turn in session:
                if not isinstance(turn, dict):
                    continue
                all_turns.append({
                    "role": str(turn.get("role", "")),
                    "content": str(turn.get("content", "")),
                })
                all_dates.append(date)
        if num_supplement:
            num_added = tmem.supplement_number_facts(
                all_turns, event_dates=all_dates, topic_extractor=_topics
            )
        if entity_supplement:
            ent_added = tmem.supplement_assistant_entities(
                all_turns, event_dates=all_dates, topic_extractor=_topics
            )
        recorded += num_added + ent_added

    agent = YoAiAgent(model=model_factory(), data_dir=out_dir / "ctx", temporal_memory=tmem)
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
    return final.strip(), {
        "events_recorded": recorded,
        "num_supplemented": num_added,
        "entities_supplemented": ent_added,
        "memory_source": memory_source,
        "tool_calls": tool_calls,
        "usage": getattr(agent.model, "total_usage", {}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "bench_data" / "longmemeval_oracle.json"))
    ap.add_argument("--type", default="")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--memory-mode", choices=["script", "model", "staged"], default="script")
    ap.add_argument("--prompt-style", choices=["basic", "enhanced"], default="basic",
                    help="enhanced=借鉴AMBRACE分类清单+数字专类+逐字依据的抽取提示")
    ap.add_argument("--num-supplement", action="store_true",
                    help="无条件用正则补充数字事实（借鉴AMBRACE，补模型自记漏掉的句中数字)")
    ap.add_argument("--entity-supplement", action="store_true",
                    help="补充助手话编号列表里的专有实体（assistant 类专名漏记）")
    ap.add_argument("--memory-temperature", type=float, default=0.1,
                    help="记忆阶段模型温度（默认0.1：全量A/B证明+8.8pp显著，见SELF-MEMORY-STABILITY.md）；"
                         "答题阶段保持默认。传 --memory-temperature=-1 可禁用（不传温度字段）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cases = json.load(open(args.data, encoding="utf-8"))
    if args.type:
        cases = [c for c in cases if c.get("question_type") == args.type]
    sample = _sample(cases, args.limit, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    config = {
        "benchmark": "LongMemEval", "mode": "retrieval (YoAi TemporalMemory)",
        "split": "oracle", "question_type": args.type, "n": len(sample), "seed": args.seed,
        "answer_model": "deepseek/deepseek-v4.1-flash-1017 (suanli.cn, free)",
        "memory": "YoAi TemporalMemory (YoAi 内覆盖层，未改原 Core)",
        "memory_mode": args.memory_mode,
        "prompt_style": args.prompt_style,
        "memory_temperature": args.memory_temperature,
        "memory_phase": {
            "model": "model reads transcript once -> remember_event (用户+助手一起记)",
            "staged": "two passes with INPUT isolation: user-only transcript then assistant-only transcript",
            "script": "haystack turns -> remember_from_transcript (deterministic, no model call)",
        }[args.memory_mode],
        "answer_phase": "model + 关联工具(all_topics/summarize_theme/related_events) tool loop",
    }
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 断点续跑：每题追加写 progress.jsonl，重跑时跳过已完成的题。
    # 事故背景：500 题跑到 106 题时断网，旧版只在最后统一写文件 → 106 题白跑。
    progress_path = out / "progress.jsonl"
    done: dict[str, dict] = {}
    if progress_path.exists():
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                done[rec["question_id"]] = rec
            except (json.JSONDecodeError, KeyError):
                continue
        print(f"RESUME: 已完成 {len(done)} 题，跳过", flush=True)

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
        answer_factory = lambda: GatewayModelProvider(SuanliAdapter())
        mem_factory = (
            (lambda: GatewayModelProvider(SuanliAdapter(temperature=args.memory_temperature)))
            if args.memory_temperature is not None and args.memory_temperature >= 0
            else answer_factory
        )
        try:
            answer, meta = asyncio.run(
                _answer(case, case_dir, answer_factory,
                        memory_mode=args.memory_mode, prompt_style=args.prompt_style,
                        num_supplement=args.num_supplement,
                        entity_supplement=args.entity_supplement,
                        memory_model_factory=mem_factory)
            )
        except Exception as exc:
            answer, meta = "", {"error": f"{type(exc).__name__}: {exc}"}
        trace = {
            "question_id": qid, "question_type": case["question_type"],
            "question": case["question"], "answer": str(case["answer"]), "hypothesis": answer,
            **meta,
        }
        hyps.append({"question_id": qid, "hypothesis": answer})
        traces.append(trace)
        # 立即追加落盘，断网/中断不丢已完成结果
        with progress_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"question_id": qid, "hypothesis": answer,
                                 "trace": trace}, ensure_ascii=False) + "\n")
            fh.flush()
        print(f"[{i}/{len(sample)}] {qid} tools={meta.get('tool_calls')} -> {answer[:50]!r}",
              flush=True)

    (out / "hypotheses.jsonl").write_text(
        "\n".join(json.dumps(h, ensure_ascii=False) for h in hyps), encoding="utf-8"
    )
    (out / "traces.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in traces), encoding="utf-8"
    )
    print(f"WROTE {out / 'hypotheses.jsonl'} ({len(hyps)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
