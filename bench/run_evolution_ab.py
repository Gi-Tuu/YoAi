"""进化对照实验 A/B/C/D · 进化机制接线版（EVOLUTION-WIRING）。

与旧版区别（旧版见 git/文档 EVOLUTION-GAP-ANALYSIS）：
- 专家有**真实工具白名单**（接线 1）：ExpertSpec.tools 经 ExpertModelProvider.tools_for
  → YoAiAgent tool_filter 生效，不同专家执行时工具集真的不同；
- 评测走 **retrieval 模式**（接线 2）：haystack 写入 TemporalMemory，模型用工具检索答题
  （oracle 长上下文下工具无意义，测不出差异）；
- **父子成对验证样本**（接线 3）：每个专家有父版本（工具更少），父子各跑同一批题，
  证据 parent_id 指向父节点，让 BenchmarkLab 能成对评测。

四组（docs/REVIEW-AND-BENCHMARK-PLAN.md §5.2）：
- A 固定 Agent：单一 root（全部工具），无路由
- B 线性自进化：单链只留最新节点（全部工具）
- C 分支但不路由：多节点都在，固定选 root
- D 完整：指纹路由，专家带不同工具白名单

约束：所有改动在 YoAi 内，原 Core 只读、零改动。

用法：
  python bench/run_evolution_ab.py --group D --limit 30 --out bench_results/evo2-D-30
  python bench/run_evolution_ab.py --group all --limit 500 --out bench_results/evo2-all-500
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
from yai_core.memory import SqliteStore  # noqa: E402

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.evidence import ExecutionEvidenceCollector  # noqa: E402
from yoai.evidence.models import SAMPLE_VALIDATION  # noqa: E402
from yoai.evidence.store import EvidenceStore  # noqa: E402
from yoai.evolution.fingerprint import fingerprint  # noqa: E402
from yoai.evolution.archive import EvolutionArchive  # noqa: E402
from yoai.evolution.models import ExpertSpec  # noqa: E402
from yoai.evolution.router import ExpertRouter, RouteDecision  # noqa: E402
from yoai.models import GatewayModelProvider, SuanliAdapter  # noqa: E402
from yoai.models.expert_provider import ExpertModelProvider  # noqa: E402
from yoai.temporal_memory import TemporalMemory  # noqa: E402

GROUPS = ("A", "B", "C", "D")

# 工具白名单：这是"真实能力差异"的核心。不同专家只能用不同工具。
ALL_MEMORY_TOOLS = {
    "remember_event", "events_between", "facts_by_tag",
    "related_events", "summarize_theme", "all_topics",
    "recall_fact", "list_facts",
}
AGGREGATE_TOOLS = {"related_events", "summarize_theme", "all_topics", "list_facts"}
TIME_TOOLS = {"events_between", "facts_by_tag", "list_facts", "all_topics"}
BASIC_TOOLS = {"list_facts", "recall_fact"}   # 父版本/弱配置：只有基础查询

_ROOT_SPEC = ExpertSpec(
    strategy_bias="direct", tools=tuple(sorted(ALL_MEMORY_TOOLS)),
    prompt_suffix="你是通用助手。用可用工具查记忆后简洁回答。",
    capability_tags=(),
)
_EXPERTS: dict[str, ExpertSpec] = {
    "memory_expert": ExpertSpec(
        strategy_bias="direct", tools=tuple(sorted(ALL_MEMORY_TOOLS)),
        prompt_suffix="你擅长时间推理。先按时间范围定位事件，再引用具体日期回答。",
        capability_tags=("memory", "temporal"),
    ),
    "research_expert": ExpertSpec(
        strategy_bias="direct", tools=tuple(sorted(ALL_MEMORY_TOOLS)),
        prompt_suffix="你擅长跨会话聚合。先列全部主题，再汇总相关事件后回答。",
        capability_tags=("multi_session", "research", "aggregation"),
    ),
}
# 父版本（弱能力）：只有基础工具，用于父子成对验证
_PARENT_SPEC = ExpertSpec(
    strategy_bias="direct", tools=tuple(sorted(BASIC_TOOLS)),
    prompt_suffix="用基础记忆查询回答问题。",
    capability_tags=(),
)

_TAG_LEXICON = {
    "memory": ("remember", "recall", "mentioned", "said", "记得", "回忆", "偏好"),
    "temporal": ("ago", "when", "last", "weeks", "months", "前", "何时"),
    "multi_session": ("total", "all", "across", "how many", "总共", "所有"),
    "research": ("what", "which", "who", "where", "什么", "哪个"),
    "aggregation": ("total", "sum", "average", "how much", "总共", "合计"),
}


def _iso_date(raw: str) -> str:
    raw = str(raw or "").strip()
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})\s*(?:\(\w+\))?\s*(\d{2}:\d{2})?", raw)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4) or '00:00'}:00" if m else raw


def _topics(text: str) -> list[str]:
    low = text.lower()
    words = {
        "jewelry": ["jewelry", "necklace", "earring", "ring"],
        "travel": ["trip", "travel", "camping", "hiking", "road trip"],
        "money": ["$", "earn", "spend", "sold", "price"],
        "family": ["sister", "brother", "sibling", "parent"],
        "food": ["coffee", "restaurant", "grocery", "bake"],
    }
    return [k for k, ws in words.items() if any(w in low for w in ws)]


def build_archive(group: str, path: Path) -> tuple[EvolutionArchive, ExpertRouter | None]:
    """按组构建档案（跨题复用，节点 id 稳定），含父子成对结构。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    ar = EvolutionArchive(path)
    root = ar.create_root("root", _ROOT_SPEC)

    def get_or_create(name: str, spec: ExpertSpec, parent_id: str):
        for n in ar.list_nodes():
            if n.name == name:
                return n
        return ar.create_child(parent_id, name, spec)

    if group == "A":
        return ar, None   # 固定 root，全部工具，无路由

    if group == "B":
        # 线性：root→memory→research，只留最新 research active
        mem = get_or_create("memory_expert", _EXPERTS["memory_expert"], root.id)
        res = get_or_create("research_expert", _EXPERTS["research_expert"], mem.id)
        for n in (root, mem):
            if n.lifecycle == "active":
                ar.transition(n.id, "retired")
        for target in ("probation", "active"):
            if res.lifecycle != target and target == "probation" and res.lifecycle == "candidate":
                ar.transition(res.id, "probation")
            if res.lifecycle == "probation" and target == "active":
                ar.transition(res.id, "active")
        router = ExpertRouter(ar, tag_lexicon=_TAG_LEXICON)
        return ar, router

    # C / D：多节点 active，各有父版本（弱工具）作对照。
    # 父版本保持 retired：档案保留（BenchmarkLab 按 expert_id/parent_id 取样本，
    # 不看 lifecycle），但不参与 routing_candidates（只 active），避免被误选。
    for name, spec in _EXPERTS.items():
        parent = get_or_create(f"parent_{name}", _PARENT_SPEC, root.id)
        child = get_or_create(name, spec, parent.id)
        if child.lifecycle == "candidate":
            ar.transition(child.id, "probation")
        if child.lifecycle == "probation":
            ar.transition(child.id, "active")
        if parent.lifecycle == "candidate":
            ar.transition(parent.id, "probation")
            ar.transition(parent.id, "retired")

    if group == "C":
        router = FixedRootRouter(ar, tag_lexicon=_TAG_LEXICON)
    else:
        router = ExpertRouter(ar, tag_lexicon=_TAG_LEXICON)
    return ar, router


class FixedRootRouter(ExpertRouter):
    """C 组：保留分支但固定选根。"""

    def route(self, task: str) -> RouteDecision:
        root = self.archive.root
        fp = fingerprint(task, tag_lexicon=self.tag_lexicon)
        d = RouteDecision(
            task=task, fingerprint=fp,
            selected_id=root.id if root else None,
            selected_name=root.name if root else "",
            scores={}, reason="C组固定选根（分支不自适应）", fallback=True,
        )
        self._last_decision = d
        return d


class ForcedExpertRouter(ExpertRouter):
    """父子成对验证：强制按指定节点执行（父节点 retired 也要能跑）。"""

    def __init__(self, archive: EvolutionArchive, node_id: str,
                 tag_lexicon=None) -> None:
        super().__init__(archive, tag_lexicon=tag_lexicon)
        self.node_id = node_id

    def route(self, task: str) -> RouteDecision:
        node = self.archive.get(self.node_id)
        fp = fingerprint(task, tag_lexicon=self.tag_lexicon)
        d = RouteDecision(
            task=task, fingerprint=fp,
            selected_id=node.id if node else None,
            selected_name=node.name if node else "",
            scores={}, reason="父子成对验证：强制指定节点", fallback=False,
        )
        self._last_decision = d
        return d


def _sample(cases: list[dict], limit: int, seed: int) -> list[dict]:
    out = list(cases)
    random.Random(seed).shuffle(out)
    return out[:limit]


def _write_memory(case: dict, tmem: TemporalMemory) -> int:
    """记忆阶段：haystack 用户话确定性写入（ retrieval 设置）。"""
    dates = case.get("haystack_dates") or []
    turns: list[dict[str, str]] = []
    dates_flat: list[str] = []
    for idx, session in enumerate(case.get("haystack_sessions") or []):
        date = _iso_date(str(dates[idx]) if idx < len(dates) else "")
        for turn in session:
            if not isinstance(turn, dict):
                continue
            if str(turn.get("role", "")) != "user":
                continue
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            # 截取事实陈述（去请求噪音）
            fact = content
            m = re.search(r"[。！？.!?]", fact)
            if m and m.start() >= 6:
                fact = fact[:m.start()].strip()
            turns.append({"role": "user", "content": fact[:400]})
            dates_flat.append(date)
    return tmem.remember_from_transcript(turns, event_dates=dates_flat, topic_extractor=_topics)


async def _answer_one(
    case: dict, group: str, out_dir: Path, shared_dir: Path,
    memory_mode: str = "script", memory_temperature: float = 0.1,
    forced_expert_id: str = "",
) -> tuple[str, dict]:
    """单题：写记忆 → 按组工具白名单 retrieval 答题 → 证据落 validation。

    memory_mode=script: 确定性写入（旧版）；=model: 低温模型自记（复用已验证的
    _memory_phase_model，temperature=0.1 消除自记模式随机切换）。四组用同一记忆逻辑，
    差异只在答题工具白名单——保证对照公平。
    """
    ev_store = EvidenceStore(shared_dir / "evidence.json")
    ar, router = build_archive(group, shared_dir / "archive.json")

    base = GatewayModelProvider(SuanliAdapter())   # 工具模式（答题阶段）
    if forced_expert_id:
        router = ForcedExpertRouter(ar, forced_expert_id, tag_lexicon=_TAG_LEXICON)
    model = ExpertModelProvider(base, router, ar) if router else base

    # 记忆阶段：确定性 或 低温模型自记（四组一致）
    tmem = TemporalMemory(out_dir / "tmem.json")
    if memory_mode == "model":
        from run_longmemeval_retrieval import _memory_phase_model
        mem_adapter = SuanliAdapter(temperature=memory_temperature)
        mem_factory = lambda: GatewayModelProvider(mem_adapter)
        n_mem, mem_source = await _memory_phase_model(case, tmem, out_dir, mem_factory)
    else:
        n_mem = _write_memory(case, tmem)
        mem_source = "script"

    # 工具过滤：D 组按专家白名单，其它组不过滤（全部工具）
    tool_filter = (model.tools_for
                   if router is not None and (group == "D" or forced_expert_id)
                   else None)
    agent = YoAiAgent(
        model=model, data_dir=out_dir / "ctx", temporal_memory=tmem,
        tool_filter=tool_filter,
    )

    collector = ExecutionEvidenceCollector()
    qdate = _iso_date(str(case.get("question_date") or ""))
    question = case["question"]
    if qdate:
        question = f"[当前日期：{qdate}]\n{question}\n\n请用记忆工具检索后回答。"
    fp = fingerprint(question, tag_lexicon=_TAG_LEXICON)

    final = ""
    tool_calls: list[str] = []
    async for event in agent.astream(question):
        collector.observe(event)
        if event.type == EventType.TOOL_CALL:
            tool_calls.append(str(event.data.get("tool", "")))
        if event.type == EventType.DONE:
            final = str(event.data.get("final_text") or "")

    evidence = collector.finish(
        session_id=f"evo2-{group}-{'parent' if forced_expert_id else 'child'}", task=question,
        task_fingerprint=fp.key, fingerprint_tags=fp.tags,
        sample_class=SAMPLE_VALIDATION,
        expert_id=getattr(model, "last_expert_id", None) or "root",
        parent_id=getattr(model, "last_parent_id", None),
        usage_override=getattr(base, "total_usage", None),
        route_decision=(router.last_decision.to_dict() if router and getattr(router, "last_decision", None) else None),
    )
    ev_store.add(evidence)
    return final.strip(), {
        "group": group, "variant": "parent" if forced_expert_id else "child",
        "expert_id": evidence.expert_id, "parent_id": evidence.parent_id,
        "mem_events": n_mem, "mem_source": mem_source,
        "tool_calls": tool_calls, "status": evidence.status,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "bench_data" / "longmemeval_oracle.json"))
    ap.add_argument("--group", choices=[*GROUPS, "all"], default="all")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--offset", type=int, default=0,
                    help="从打乱后的样本中跳过前 N 题（分片并行用，seed 与 limit 需一致）")
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--out", required=True)
    ap.add_argument("--memory-mode", choices=["script", "model"], default="script",
                    help="记忆阶段：script=确定性(旧版)；model=低温模型自记(重验进化用)")
    ap.add_argument("--memory-temperature", type=float, default=0.1,
                    help="记忆阶段温度（model 模式生效，默认0.1）")
    args = ap.parse_args()

    cases = json.load(open(args.data, encoding="utf-8"))
    sample = _sample(cases, args.offset + args.limit, args.seed)[args.offset:]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    groups = GROUPS if args.group == "all" else (args.group,)

    config = {
        "benchmark": "LongMemEval", "experiment": "evolution-wiring A/B/C/D",
        "groups": list(groups), "n": len(sample), "seed": args.seed,
        "answer_model": "deepseek/deepseek-v4.1-flash-1017 (suanli.cn, free)",
        "mode": "retrieval (TemporalMemory) + expert tool whitelist",
        "memory_mode": args.memory_mode,
        "memory_temperature": args.memory_temperature if args.memory_mode == "model" else None,
        "tool_whitelists": {
            "root": sorted(ALL_MEMORY_TOOLS), "memory_expert": sorted(ALL_MEMORY_TOOLS),
            "research_expert": sorted(ALL_MEMORY_TOOLS), "parent_*": sorted(BASIC_TOOLS),
        },
        "offset": args.offset,
        "note": "接线版：白名单生效+retrieval+父子成对；D组专家工具不同，A/B/C全工具",
    }
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for group in groups:
        gdir = out / group
        gdir.mkdir(parents=True, exist_ok=True)
        shared = gdir / "shared"
        shared.mkdir(exist_ok=True)
        progress = gdir / "progress.jsonl"
        done: dict[str, dict] = {}
        if progress.exists():
            for line in progress.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        rec = json.loads(line)
                        done[f"{rec['question_id']}:{rec.get('variant', 'child')}"] = rec
                    except (json.JSONDecodeError, KeyError):
                        pass
        print(f"[{group}] RESUME {len(done)}/{len(sample)}", flush=True)

        hyps: list[dict] = []
        traces: list[dict] = []
        for i, case in enumerate(sample, 1):
            qid = case["question_id"]
            ar_pair, _ = (build_archive(group, shared / "archive.json")
                          if group in ("C", "D") else (None, None))
            variants: list[tuple[str, str]] = [("child", "")]
            for variant, forced in variants:
                key = f"{qid}:{variant}"
                if key in done:
                    rec = done[key]
                    hyps.append({"question_id": qid, "hypothesis": rec.get("hypothesis", "")})
                    traces.append(rec.get("trace", {}))
                    continue
                try:
                    answer, meta = asyncio.run(_answer_one(
                        case, group, gdir / f"case_{i}_{variant}", shared,
                        memory_mode=args.memory_mode,
                        memory_temperature=args.memory_temperature,
                        forced_expert_id=forced,
                    ))
                except Exception as exc:
                    answer, meta = "", {"error": f"{type(exc).__name__}: {exc}"}
                trace = {
                    "question_id": qid, "variant": variant,
                    "question_type": case["question_type"],
                    "question": case["question"], "answer": str(case["answer"]),
                    "hypothesis": answer, **meta,
                }
                hyps.append({"question_id": qid, "hypothesis": answer})
                traces.append(trace)
                with progress.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"question_id": qid, "variant": variant,
                                         "hypothesis": answer, "trace": trace},
                                        ensure_ascii=False) + "\n")
                    fh.flush()
                print(f"[{group} {i}/{len(sample)}] {qid} {variant} "
                      f"expert={meta.get('expert_id')} tools={len(meta.get('tool_calls', []))} "
                      f"-> {answer[:35]!r}", flush=True)
                # 子跑完后才知道父节点 id，追加强制父版本形成成对验证样本
                if variant == "child" and ar_pair is not None:
                    node = ar_pair.get(str(meta.get("expert_id", "")))
                    if node and node.parent_id:
                        variants.append(("parent", node.parent_id))

        (gdir / "hypotheses.jsonl").write_text(
            "\n".join(json.dumps(h, ensure_ascii=False) for h in hyps), encoding="utf-8"
        )
        (gdir / "traces.jsonl").write_text(
            "\n".join(json.dumps(t, ensure_ascii=False) for t in traces), encoding="utf-8"
        )
        print(f"[{group}] WROTE {gdir / 'hypotheses.jsonl'} ({len(hyps)})", flush=True)

    print(f"DONE all groups -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
