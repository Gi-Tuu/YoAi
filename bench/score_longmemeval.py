"""LongMemEval 官方评分口径的本地实现（judge 换 deepseek，prompt 原样保留）。

来源：LongMemEval 官方 src/evaluation/evaluate_qa.py（已核查源码）。
本文件**逐字保留**官方的 get_anscheck_prompt（6 类题型 + 弃用问句的 prompt 模板、
yes/no 判定、temperature=0、max_tokens=10），只把传输层从 openai SDK 换成
YoAi 已有的 post_json（因为本地 openai 库是 3.9，无 v1 OpenAI 类，且需走算里网关）。

差异（必须如实标注）：官方 judge 模型 = gpt-4o-2024-08-06；本实现 judge =
deepseek/deepseek-v4.1-flash-1017（算里免费）。得分是"官方评分口径 + 替代 judge"，
不可直接与官方榜单分数对比。

用法：
  python bench/score_longmemeval.py --hyp bench_results/xxx/hypotheses.jsonl \
      --ref bench_data/longmemeval_oracle.json --out bench_results/xxx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.models.http_base import read_env_file, post_json  # noqa: E402

def _core_env():
    explicit = os.environ.get("YAI_CORE_ENV")
    if explicit:
        return Path(explicit).expanduser()
    src = os.environ.get("YAI_CORE_SRC")
    if src:
        return Path(src).expanduser() / ".env"
    # 默认回退：先试项目父目录（E:\agent\.env），不存在则用绑定的 Core 目录。
    # 历史上评分依赖环境变量 YAI_CORE_SRC，新 shell 未设时会误指向不存在的
    # E:\agent\.env，导致 judge base_url 为空 → ValueError: unknown url type。
    fallback = Path(__file__).resolve().parents[2] / ".env"
    if fallback.exists():
        return fallback
    core_env = Path(r"E:\Competition\YAI Agent Core") / ".env"
    if core_env.exists():
        return core_env
    return fallback


CORE_ENV = _core_env()
JUDGE_MODEL = "deepseek/deepseek-v4.1-flash-1017"


# ===== 以下为官方 evaluate_qa.py 的 get_anscheck_prompt，逐字保留 =====
def get_anscheck_prompt(task, question, answer, response, abstention=False):
    if not abstention:
        if task in ['single-session-user', 'single-session-assistant', 'multi-session']:
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'temporal-reasoning':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'knowledge-update':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'single-session-preference':
            template = "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        else:
            raise NotImplementedError
    else:
        template = "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
        prompt = template.format(question, answer, response)
    return prompt
# ===== 官方 prompt 结束 =====


def judge(prompt: str) -> tuple[bool, str]:
    env = read_env_file(CORE_ENV)
    base = env.get("OPENAI_BASE_URL", "").rstrip("/")
    key = env.get("OPENAI_API_KEY", "")
    payload = {
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "n": 1, "temperature": 0,
        # 官方脚本用 max_tokens=10（gpt-4o 够）；deepseek 是思考模型，
        # 10 token 只够它写thinking、content 留空 → 这里放大到 256 才能拿到结论。
        # 这是 judge 模型替换带来的必要传输适配，评分 prompt 与 yes/no 判定不变。
        "max_tokens": 256,
    }
    data = post_json(base + "/chat/completions", payload,
                     {"Authorization": "Bearer " + key}, 60.0)
    choices = data.get("choices", [])
    msg = choices[0].get("message", {}) if choices else {}
    content = msg.get("content", "")
    text = content.strip() if isinstance(content, str) else ""
    if not text:
        # deepseek 思考模型有时把结论写进 reasoning_content，content 为 None
        reasoning = msg.get("reasoning_content", "")
        if isinstance(reasoning, str):
            text = reasoning.strip()
    return "yes" in text.lower(), text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hyp", required=True)
    ap.add_argument("--ref", default=str(ROOT / "bench_data" / "longmemeval_oracle.json"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hypotheses = [json.loads(l) for l in Path(args.hyp).read_text(encoding="utf-8").splitlines() if l.strip()]
    references = json.load(open(args.ref, encoding="utf-8"))
    qid2data = {e["question_id"]: e for e in references}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logs: list[dict] = []
    by_type: dict[str, list[int]] = {}
    for entry in hypotheses:
        qid = entry["question_id"]
        if qid not in qid2data:
            continue
        ref = qid2data[qid]
        qtype = ref["question_type"]
        prompt = get_anscheck_prompt(
            qtype, ref["question"], ref["answer"], entry["hypothesis"],
            abstention=qid.endswith("_abs"),
        )
        try:
            label, raw = judge(prompt)
        except Exception as exc:
            label, raw = False, f"JUDGE_ERROR {type(exc).__name__}: {exc}"
        entry["autoeval_label"] = {"model": JUDGE_MODEL, "label": label, "raw": raw}
        logs.append(entry)
        by_type.setdefault(qtype, []).append(1 if label else 0)
        print(f"{qid}: {'yes' if label else 'no'}  ({raw[:20]!r})", flush=True)

    total = sum(sum(v) for v in by_type.values())
    n = sum(len(v) for v in by_type.values())
    score = {
        "benchmark": "LongMemEval",
        "split": "oracle",
        "judge_model": JUDGE_MODEL,
        "judge_note": "官方 anscheck prompt 原样保留；judge 由 gpt-4o 替换为 deepseek（本地无 OpenAI key）；分数不可与官方榜单直接对比",
        "n": n,
        "accuracy": round(total / n, 4) if n else 0.0,
        "by_type": {k: {"acc": round(sum(v) / len(v), 4), "n": len(v)} for k, v in by_type.items()},
    }
    (out / "score.json").write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "score_log.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in logs), encoding="utf-8"
    )
    print("\nSCORE=", json.dumps(score, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
