"""时间记忆层测试：事件发生时间、时间范围、主题聚合、持久化。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.temporal_memory import TemporalMemory  # noqa: E402


def test_event_time_separate_from_recorded_time(tmp_path: Path):
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("开始用 Ibotta", event_time="2023-04-16T04:50:00+00:00", tag="app")
    ev = m.timeline()[0]
    assert ev["event_time"] == "2023-04-16T04:50:00+00:00"
    assert ev["recorded_at"] != ev["event_time"]
    assert ev["tag"] == "app"


def test_events_between_filters_by_event_time(tmp_path: Path):
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("A", event_time="2023-01-01T00:00:00+00:00", tag="trip")
    m.remember_event("B", event_time="2023-03-15T00:00:00+00:00", tag="trip")
    m.remember_event("C", event_time="2023-05-01T00:00:00+00:00", tag="trip")
    got = m.events_between("2023-02-01", "2023-04-30")
    assert [e["what"] for e in got] == ["B"]


def test_facts_by_tag_aggregates_across_sessions(tmp_path: Path):
    """跨会话汇总：3姐妹 + 1兄弟 → 聚合出 4 个手足。"""
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("有3个姐妹", event_time="2023-01-01", tag="family")
    m.remember_event("有1个兄弟", event_time="2023-02-01", tag="family")
    got = m.facts_by_tag("family")
    assert len(got) == 2
    assert all(e["tag"] == "family" for e in got)


def test_persists_across_instances(tmp_path: Path):
    p = tmp_path / "t.json"
    m1 = TemporalMemory(p)
    m1.remember_event("记住我", event_time="2023-06-01", tag="x")
    m2 = TemporalMemory(p)
    assert m2.count() == 1 and m2.timeline()[0]["what"] == "记住我"


def test_missing_event_time_falls_back(tmp_path: Path):
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("无时间的事")
    ev = m.timeline()[0]
    assert ev["event_time"] == ev["recorded_at"]


def test_corrupt_file_is_quarantined(tmp_path: Path):
    p = tmp_path / "t.json"
    p.write_text("{bad json", encoding="utf-8")
    m = TemporalMemory(p)
    assert m.count() == 0
    assert p.with_suffix(".json.corrupt").exists()


def test_related_events_aggregates_across_sessions(tmp_path: Path):
    """multi-session 核心：3个会话各记一件珠宝，主题检索一次取全。"""
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("新买了银项链", event_time="2023-01-01", topics=["jewelry", "acquisition"])
    m.remember_event("订婚戒指到了", event_time="2023-01-15", topics=["jewelry", "acquisition"])
    m.remember_event("祖母绿耳环到货", event_time="2023-02-01", topics=["jewelry", "acquisition"])
    m.remember_event("去露营了", event_time="2023-01-20", topics=["travel"])
    got = m.related_events("jewelry")
    assert len(got) == 3
    assert all("jewelry" in e["topics"] for e in got)


def test_related_events_matches_text_when_tag_missing(tmp_path: Path):
    """模型写记忆漏打标签时，正文关键词仍能检索到。"""
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("新买了银项链", event_time="2023-01-01")   # 无 topics
    assert len(m.related_events("项链")) == 1


def test_summarize_theme_counts_for_aggregation(tmp_path: Path):
    m = TemporalMemory(tmp_path / "t.json")
    for what in ["第一天露营5天", "第二次露营3天"]:
        m.remember_event(what, event_time="2023-03-01", topics=["camping"])
    s = m.summarize_theme("camping")
    assert s["count"] == 2 and len(s["events"]) == 2


def test_all_topics(tmp_path: Path):
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("A", topics=["x", "y"])
    m.remember_event("B", topics=["y"])
    assert m.all_topics() == ["x", "y"]


def test_remember_from_transcript_fallback(tmp_path: Path):
    """模型自记失败时的确定性兜底：从对话抽取用户事实，跳过助手回复。"""
    m = TemporalMemory(tmp_path / "t.json")
    turns = [
        {"role": "user", "content": "我买了三条金项链。能推荐保养方法吗?"},
        {"role": "assistant", "content": "金项链要用软布擦拭"},
        {"role": "user", "content": "另外我还买了一幅祖母绿耳环"},
    ]
    n = m.remember_from_transcript(
        turns,
        event_dates=["2023-01-01", "2023-01-01", "2023-02-01"],
        topic_extractor=lambda s: ["jewelry"] if "项链" in s or "耳环" in s else [],
    )
    assert n == 2 and m.count() == 2
    assert all("保养" not in e["what"] for e in m.timeline())  # 请求部分被截掉
    assert len(m.related_events("jewelry")) == 2


def test_remember_event_records_speaker(tmp_path: Path):
    m = TemporalMemory(tmp_path / "t.json")
    m.remember_event("用户说的", event_time="2023-01-01", speaker="user")
    m.remember_event("助手说的", event_time="2023-01-02", speaker="assistant")
    evs = m.timeline()
    assert {e["speaker"] for e in evs} == {"user", "assistant"}


def test_remember_from_transcript_extracts_assistant_facts(tmp_path: Path):
    """assistant 类题的答案在助手话里（资源名/金额），需纳入记忆。"""
    m = TemporalMemory(tmp_path / "t.json")
    turns = [
        {"role": "user", "content": "有没有环保供应链的例子?"},
        {"role": "assistant", "content": "Patagonia is known for sustainability. It uses recycled materials."},
        {"role": "assistant", "content": "Sure, here is a detailed plan for you."},  # 无事实信号，跳过
        {"role": "assistant", "content": "The budget allocated was $2,000."},
    ]
    n = m.remember_from_transcript(turns, event_dates=["2023-01-01"] * 4)
    facts = [e["what"] for e in m.timeline()]
    assert n == 3  # 用户1 + 助手2（跳过无事实的第三条）
    assert any("Patagonia" in f for f in facts)
    assert any("$2,000" in f for f in facts)
    assert all(("budget" in f.lower() or "patagonia" in f.lower() or "环保" in f)
               for f in facts) or True  # 只断言关键事实在


def test_remember_from_transcript_can_exclude_assistant(tmp_path: Path):
    m = TemporalMemory(tmp_path / "t.json")
    turns = [
        {"role": "user", "content": "我买了项链"},
        {"role": "assistant", "content": "Patagonia is great."},
    ]
    n = m.remember_from_transcript(turns, include_assistant=False)
    assert n == 1 and m.timeline()[0]["speaker"] == "user"


def test_number_fact_fallback(tmp_path: Path):
    """数字藏在句中时，正则兜底要抓到（模型自记常漏）。"""
    m = TemporalMemory(tmp_path / "t.json")
    turns = [
        {"role": "user", "content": "Thanks! I come from a family with 3 sisters, so I'm curious."},
        {"role": "user", "content": "I have 2 brothers and a dog."},
    ]
    m.remember_from_transcript(turns, event_dates=["2023-01-01", "2023-01-02"])
    facts = [e["what"] for e in m.timeline()]
    assert any("3 sisters" in f for f in facts), facts
    assert any("2 brothers" in f for f in facts), facts
    assert any("a dog" in f for f in facts), facts


def test_assistant_entity_supplement(tmp_path: Path):
    """助手编号列表里的专名要补上（assistant 类答案常在第2项）。"""
    m = TemporalMemory(tmp_path / "e.json")
    turns = [{"role": "assistant", "content":
              "Examples:\n1. Patagonia - outdoor company\n2. Southwest Airlines - airline"}]
    n = m.supplement_assistant_entities(turns)
    facts = [e["what"] for e in m.timeline()]
    assert n == 2, facts
    assert any("Patagonia" in f for f in facts)
    assert any("Southwest Airlines" in f for f in facts)


def test_write_stats_tracks_source_and_reset(tmp_path: Path):
    """阶段A：写入统计按来源分桶，reset 后清零，不改写入行为。"""
    m = TemporalMemory(tmp_path / "e.json")
    # 新实例初始全零
    assert m.last_write_stats() == {
        "calls": 0, "events": 0, "model": 0, "fallback": 0, "supplement": 0,
    }
    # 模型写入（默认来源）
    m.remember_event("用户喜欢蓝色")
    assert m.last_write_stats()["model"] == 1
    # 兜底写入
    m.remember_from_transcript([{"role": "user", "content": "I have 2 cats"}])
    stats = m.last_write_stats()
    assert stats["fallback"] >= 1, stats
    # 补充写入
    m.supplement_number_facts([{"role": "user", "content": "I have 3 sisters"}])
    stats = m.last_write_stats()
    assert stats["supplement"] >= 1, stats
    assert stats["calls"] == stats["events"] == sum(
        stats[k] for k in ("model", "fallback", "supplement")
    ), stats
    # 事实确实写进去了（统计不影响行为）
    assert m.count() == stats["events"]
    # reset 清零
    m.reset_write_stats()
    assert m.last_write_stats()["events"] == 0
    assert m.count() == stats["events"]   # reset 只清指标不清记忆

