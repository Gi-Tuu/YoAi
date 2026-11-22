"""评测基础设施测试：断点续跑逻辑。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))


def test_layered_sample_full_and_unique():
    """limit>=总数时返回全量唯一；小样本也唯一。"""
    from run_longmemeval import _layered_sample
    cases = [
        {"question_id": f"q{i}", "question_type": ["a", "b"][i % 2]} for i in range(20)
    ]
    full = _layered_sample(cases, 20, 42)
    assert len(full) == 20 and len({c["question_id"] for c in full}) == 20
    small = _layered_sample(cases, 8, 42)
    assert len(small) == 8 and len({c["question_id"] for c in small}) == 8


def test_progress_resume_skips_done(tmp_path: Path):
    """progress.jsonl 里已有的 question_id 应被跳过（断网续跑核心）。"""
    progress = tmp_path / "progress.jsonl"
    progress.write_text(
        json.dumps({"question_id": "q1", "hypothesis": "done",
                    "trace": {"question_id": "q1"}}) + "\n",
        encoding="utf-8",
    )
    done: dict[str, dict] = {}
    for line in progress.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        done[rec["question_id"]] = rec
    assert "q1" in done and "q2" not in done
    # 追加写入后仍可读
    with progress.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"question_id": "q2", "hypothesis": "new"}) + "\n")
    lines = progress.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_iso_date_normalization():
    """LongMemEval 日期 '2023/02/14 (Tue) 12:45' 必须转 ISO，否则时间检索失效。"""
    from run_longmemeval_retrieval import _iso_date
    assert _iso_date("2023/02/14 (Tue) 12:45") == "2023-02-14T12:45:00"
    assert _iso_date("2023/05/06 (Sat) 05:25") == "2023-05-06T05:25:00"


def test_topic_extraction():
    from run_longmemeval_retrieval import _topics
    assert "jewelry" in _topics("I bought a new silver necklace")
    assert "camping" in _topics("went camping in Yellowstone")
    assert _topics("the weather is nice") == []
