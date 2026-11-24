"""YoAi 时间记忆层（覆盖层）— 事实带"发生时间"，支持时间范围与主题聚合。

背景：LongMemEval 全量基线暴露 temporal-reasoning 37.6% / multi-session 36.8%。
根因之一：原 PersonalContext 只有 KV + datetime.now() 记录时间，
- 没有"事实发生时间"（event_time），无法回答"三周前做了什么"
- 没有按主题聚合，无法把散落多会话的信息（3姐妹+1兄弟）汇总成 4

本模块是**YoAi 内的覆盖层**，不修改原 Core 项目，也不替换 PersonalContext：
- 独立 JSON 文件，原子写 + 损坏隔离（沿用既有约定）
- event_time（事件发生）与 recorded_at（记录时刻）分离
- 提供时间范围检索、主题聚合、时间线三种查询

不假设调用方给时间：event_time 缺省时用 recorded_at，向后兼容。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TemporalMemory:
    """带事件发生时间的个人事件记忆，支持时间范围与主题聚合。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events: list[dict[str, Any]] = []
        # 写入可观测（阶段A）：只计条数/来源，不记内容、不落盘。
        # 生产侧此前无指标，"模型记0条"会悄悄发生；这里提供基线数据。
        self.write_stats: dict[str, Any] = self._empty_write_stats()
        self._load()

    @staticmethod
    def _empty_write_stats() -> dict[str, Any]:
        return {"calls": 0, "events": 0, "model": 0, "fallback": 0, "supplement": 0}

    def reset_write_stats(self) -> None:
        """每轮对话开始时清零，使 last_write_stats 反映本轮。"""
        self.write_stats = self._empty_write_stats()

    def last_write_stats(self) -> dict[str, Any]:
        """本轮写入快照：总调用/写入条数 + 按来源(model/fallback/supplement)分。

        只读返回副本，调用方改动不影响内部计数。
        """
        return dict(self.write_stats)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self._events = raw
        except (json.JSONDecodeError, OSError):
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self._events = []

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".yoai-tmem-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._events, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def remember_event(
        self,
        what: str,
        *,
        event_time: str = "",
        tag: str = "",
        topics: list[str] | None = None,
        speaker: str = "user",
        _source: str = "model",
    ) -> str:
        """记一件事。event_time 是事件发生时间（ISO 8601），缺省用当前时间。

        topics 是细粒度主题标签（如 ["jewelry", "acquisition"]）——粗 tag 只按题型分，
        无法把散落多会话的同类事件聚起来（LongMemEval multi-session 36.8% 的根因）。
        speaker 区分"用户说的"与"助手说的"——LongMemEval assistant 类题问的是
        "你之前提到的资源/结论"，答案在助手话里；旧版只记用户话导致该类暴跌。
        """
        recorded = _now()
        self._events.append({
            "what": str(what),
            "event_time": str(event_time) if event_time else recorded,
            "recorded_at": recorded,
            "tag": str(tag),
            "topics": [str(t) for t in (topics or [])],
            "speaker": str(speaker) if speaker in ("user", "assistant") else "user",
        })
        self._save()
        # 旁路计数：不记内容、不影响写入行为
        self.write_stats["calls"] += 1
        self.write_stats["events"] += 1
        bucket = _source if _source in ("model", "fallback", "supplement") else "model"
        self.write_stats[bucket] += 1
        return f"已记住事件：{what}"

    def events_between(self, start: str, end: str) -> list[dict[str, Any]]:
        """查 [start, end] 区间内发生的事件（按 event_time 过滤，字典序可比 ISO 8601）。"""
        lo, hi = str(start), str(end)
        out = [e for e in self._events if lo <= e["event_time"] <= hi]
        return sorted(out, key=lambda e: e["event_time"])

    def facts_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """按主题聚合某类事实（跨会话汇总用）。"""
        return [e for e in self._events if e["tag"] == tag]

    def forget(self, what: str, *, tag: str = "") -> int:
        """删除匹配的事件/事实，返回删除条数（0=没有匹配）。

        what **精确匹配** what 字段（模型应先 list_facts / facts_by_tag 拿到
        准确原文再删，避免误删）。tag 可选进一步收窄；删除不可恢复。
        """
        needle = str(what).strip()
        if not needle:
            return 0
        matched = [
            e for e in self._events
            if e.get("what") == needle and (not tag or e.get("tag") == tag)
        ]
        if not matched:
            return 0
        self._events = [e for e in self._events if e not in matched]
        self._save()
        return len(matched)

    def recent_events(self, n: int = 10) -> list[dict[str, Any]]:
        """最近 n 条事件（按记录时间倒序），删除前核对精确原文用。"""
        try:
            limit = max(1, min(50, int(n)))
        except (TypeError, ValueError):
            limit = 10
        return list(reversed(self._events[-limit:]))

    def timeline(self) -> list[dict[str, Any]]:
        """返回按事件发生时间排序的完整时间线。"""
        return sorted(self._events, key=lambda e: e["event_time"])

    def related_events(self, topic: str) -> list[dict[str, Any]]:
        """按细粒度主题取所有相关事件（跨会话聚合的核心）。

        同时匹配 topics 标签与事件正文关键词，避免模型写记忆时漏打标签。
        """
        key = str(topic).strip().lower()
        if not key:
            return []
        out = []
        for e in self._events:
            in_topics = any(key in t.lower() for t in e.get("topics", []))
            in_text = key in e["what"].lower()
            if in_topics or in_text:
                out.append(e)
        return sorted(out, key=lambda e: e["event_time"])

    def summarize_theme(self, topic: str) -> dict[str, Any]:
        """主题聚合摘要：列出该主题下所有事件 + 数量，供模型做"总共几件"类求和。"""
        events = self.related_events(topic)
        return {
            "topic": topic,
            "count": len(events),
            "events": [
                {"what": e["what"], "event_time": e["event_time"]} for e in events
            ],
        }

    def all_topics(self) -> list[str]:
        """列出所有已知主题（帮助模型发现该查什么）。"""
        seen: set[str] = set()
        for e in self._events:
            for t in e.get("topics", []):
                if t:
                    seen.add(t)
        return sorted(seen)

    def remember_from_transcript(
        self,
        turns: list[dict[str, str]],
        *,
        event_dates: list[str] | None = None,
        topic_extractor=None,
        include_assistant: bool = True,
    ) -> int:
        """从对话轮次里确定性抽取事实并写入（模型自记失败时的兜底保障）。

        产品背景：实测 deepseek 思考模型在读长对话时，40% 的题会把 reasoning
        泄漏成答案、一个工具都不调，导致记忆为空。记忆写入不能完全依赖模型自愿，
        需要确定性兜底保证"对话里的事实不丢"。

        include_assistant=True 时也抽取助手回复里的事实性句子——LongMemEval 的
        assistant 类题问"你之前提到的资源/结论"，答案只在助手话里。旧版只记用户话，
        导致该类在 retrieval 模式暴跌 67.8pp。助手话只取含数字/URL/明确结论的句子，
        避免把整段建议塞进记忆造成噪音。

        turns: [{"role": "user"/"assistant", "content": "..."}]
        event_dates: 每轮对应的 ISO 日期（可选）
        topic_extractor: callable(content)->list[str]，缺省只按空 topics 写
        """
        import re
        added = 0
        dates = event_dates or []

        # 数字事实正则兜底（借鉴 AMBRACE response_parser.py 的关键词抽取思路）：
        # 模型自记常把数字藏在句子中段而漏掉（如 "I come from a family with 3 sisters"
        # 被摘成前半段）。用规则从整段话里抓"数字+名词"，不受分句位置限制。
        # 纯函数、零模型、逐字保留数字——与 AMBRACE "内容不造句"护栏一致。
        _NUM_FACT = re.compile(
            r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
            r"(sisters?|brothers?|siblings?|children|kids|cats?|dogs?|pets?|"
            r"necklaces?|earrings?|rings?|bracelets?|mugs?|cups?|books?|courses?|"
            r"trips?|miles?|days?|weeks?|months?|years?|hours?|minutes?)\b",
            re.IGNORECASE,
        )
        _WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
                     "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                     "ten": 10, "eleven": 11, "twelve": 12}

        for i, turn in enumerate(turns):
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", ""))
            content = str(turn.get("content", "")).strip()
            if not content or role not in ("user", "assistant"):
                continue

            if role == "assistant" and not include_assistant:
                continue

            # 取第一个分句边界（。！？!?.）之前的第一段；太短说明整句是请求/寒暄，跳过
            m = re.search(r"[。！？.!?]", content)
            if m:
                first = content[:m.start()].strip()
                if len(first) < 6:
                    continue
            else:
                first = content
            fact = first[:400]

            if role == "assistant":
                # 只记助手话里有"事实信号"的句子：数字/金额/百分号/URL/专有名词
                # 排除 "Sure, here's..."/"As an AI..." 这类无信息的开场白
                _NO_FACT_PREFIX = (
                    "sure", "certainly", "of course", "as an ai", "i'd be happy",
                    "i would be happy", "here's", "here is", "great question",
                    "absolutely", "thanks", "thank you", "i understand",
                )
                low = fact.lower()
                if low.startswith(_NO_FACT_PREFIX):
                    continue
                has_fact = bool(re.search(r"[$€£]|\d+%|https?://|www\.|\b[A-Z][a-z]{2,}", fact))
                if not has_fact or len(fact) > 300:
                    continue

            date = str(dates[i]) if i < len(dates) else ""
            topics = topic_extractor(fact) if topic_extractor else []
            self.remember_event(fact, event_time=date, topics=topics, speaker=role,
                                _source="fallback")
            added += 1

            # 数字兜底：从整段话（不只 first）抓"数字+名词"，逐字保留原话短语。
            # 直击模型自记把句中数字漏掉的问题（如 "family with 3 sisters"）。
            if role == "user":
                existing = {e["what"].lower() for e in self._events}
                for mnum in _NUM_FACT.finditer(content):
                    phrase = mnum.group(0).strip()
                    # 造一条可核对的事实：保留数字与名词，附最简上下文
                    num_fact = f"用户提到 {phrase}"
                    if num_fact.lower() in existing:
                        continue
                    self.remember_event(
                        num_fact, event_time=date,
                        topics=(topic_extractor(num_fact) if topic_extractor else []),
                        speaker="user", _source="fallback",
                    )
                    existing.add(num_fact.lower())
                    added += 1
        return added

    def supplement_number_facts(
        self,
        turns: list[dict[str, str]],
        *,
        event_dates: list[str] | None = None,
        topic_extractor=None,
    ) -> int:
        """无条件补充数字事实（模型自记后也跑，作为独立补充层）。

        与 fallback 的区别：fallback 只在模型记 0 条时整体接管；这里是**叠加**——
        模型记了 20 条寒暄但漏了 "3 sisters"，本方法从整段话里按规则补上数字，
        不删改模型已记的内容。纯函数、逐字保留数字。
        """
        import re
        _NUM_FACT = re.compile(
            r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
            r"(sisters?|brothers?|siblings?|children|kids|cats?|dogs?|pets?|"
            r"necklaces?|earrings?|rings?|bracelets?|mugs?|cups?|books?|courses?|"
            r"trips?|miles?|days?|weeks?|months?|years?|hours?|minutes?)\b",
            re.IGNORECASE,
        )
        added = 0
        dates = event_dates or []
        existing = {e["what"].lower() for e in self._events}
        for i, turn in enumerate(turns):
            if not isinstance(turn, dict) or str(turn.get("role", "")) != "user":
                continue
            content = str(turn.get("content", "")).strip()
            date = str(dates[i]) if i < len(dates) else ""
            for m in _NUM_FACT.finditer(content):
                phrase = m.group(0).strip()
                num_fact = f"用户提到 {phrase}"
                if num_fact.lower() in existing:
                    continue
                self.remember_event(
                    num_fact, event_time=date,
                    topics=(topic_extractor(num_fact) if topic_extractor else []),
                    speaker="user", _source="supplement",
                )
                existing.add(num_fact.lower())
                added += 1
        return added

    def supplement_assistant_entities(
        self,
        turns: list[dict[str, str]],
        *,
        event_dates: list[str] | None = None,
        topic_extractor=None,
    ) -> int:
        """补充助手话编号列表里的专有实体（assistant 类题的答案常在第2+项）。

        借鉴 AMBRACE "内容不造句"护栏：逐字取实体名，不改写、不脑补。
        实证：assistant 失败题中 24/29 的助手话含编号/多实体列举，
        模型自记常只记第1项、漏掉答案需要的第2项（如 Patagonia 记了、Southwest 漏了）。
        只抓编号列表项开头的专名（如 "1. Patagonia - ..." "2. Southwest Airlines - ..."），
        不抓大段描述，避免噪音。
        """
        import re
        _LIST_ITEM = re.compile(
            r"(?:^|\n)\s*\d+[\.\)]\s+"       # 行首编号 1. / 1)
            r"([A-Z][A-Za-z0-9&'\-]*(?:\s+[A-Z][A-Za-z0-9&'\-]*){0,3})"  # 专名(最多4词)
            r"\s*[-–:]"
        )
        added = 0
        dates = event_dates or []
        existing = {e["what"].lower() for e in self._events}
        for i, turn in enumerate(turns):
            if not isinstance(turn, dict) or str(turn.get("role", "")) != "assistant":
                continue
            content = str(turn.get("content", "")).strip()
            date = str(dates[i]) if i < len(dates) else ""
            for m in _LIST_ITEM.finditer(content):
                name = m.group(1).strip()
                if not name or len(name) > 60:
                    continue
                # 跳过明显的句子开头（句子不会在专名后紧跟 - 或 :）
                ent_fact = f"助手提到 {name}"
                if ent_fact.lower() in existing:
                    continue
                self.remember_event(
                    ent_fact, event_time=date,
                    topics=(topic_extractor(ent_fact) if topic_extractor else []),
                    speaker="assistant", _source="supplement",
                )
                existing.add(ent_fact.lower())
                added += 1
        return added

    def count(self) -> int:
        return len(self._events)
