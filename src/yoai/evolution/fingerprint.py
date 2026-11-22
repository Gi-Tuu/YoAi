"""任务指纹提取 · M1。

作用：把一段任务文本转成稳定的结构化指纹，供专家路由做"一次匹配"。
设计要点（见 docs/EVOLUTION-PLAN.md §4 M1）：
- 纯函数、零第三方依赖，独立可测。
- 规范化思路对齐 Core 的 discovery/scoring.py（NFKC + 小写 + 中文单字/bigram），
  但不 import Core 内部模块——YoAi 是外层产品，保持独立。
- 能力标签词典可注入；结构信号（多步骤/行动/模糊/提问）供策略偏好匹配。
- 同一任务永远得到同一指纹 key（稳定哈希），可用于证据留痕与样本隔离。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

_LATIN_WORD = re.compile(r"[a-z0-9]+")
_CJK_CHAR = re.compile(r"[一-鿿]")

# 默认能力标签词典：tag -> 命中词（任一出现即命中该标签）。
# 宿主可注入自己的词典覆盖；这里只放最小通用集，避免主观大词表制造误命中。
DEFAULT_TAG_LEXICON: dict[str, tuple[str, ...]] = {
    "writing": ("写", "撰写", "文章", "文案", "总结", "摘要", "润色", "write", "draft"),
    "coding": ("代码", "编程", "函数", "调试", "重构", "bug", "code", "refactor"),
    "research": ("搜索", "查询", "检索", "查一下", "调研", "资料", "search", "find"),
    "planning": ("计划", "规划", "拆解", "步骤", "安排", "目标", "plan", "schedule"),
    "memory": ("记住", "回忆", "偏好", "记得", "取回", "remember", "recall"),
    "chat": ("你好", "聊聊", "闲聊", "hi", "hello"),
}

# 结构信号词：供 ExpertSpec.strategy_bias 匹配
_MULTI_STEP = ("然后", "再", "接着", "之后", "同时", "最后", "先", "分步", "步骤")
_ACTION = ("创建", "删除", "修改", "保存", "打开", "发送", "运行", "执行", "归档", "调")
_VAGUE = ("一下", "某个", "那个", "大概", "看看", "随便")
_QUESTION = ("吗", "？", "?", "什么", "怎么", "为什么", "是否")


@dataclass(frozen=True)
class TaskFingerprint:
    """任务指纹：归一文本 + token + 能力标签 + 结构信号 + 稳定 key。"""

    original: str
    normalized: str
    unigrams: tuple[str, ...]
    bigrams: tuple[str, ...]
    tags: tuple[str, ...]
    signals: tuple[str, ...]
    key: str

    def to_dict(self) -> dict[str, object]:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "tags": list(self.tags),
            "signals": list(self.signals),
            "key": self.key,
        }


def normalize(text: str | None) -> str:
    """NFKC + 小写 + 标点折叠为空格，保留中文与拉丁字母数字。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    kept: list[str] = []
    for ch in text:
        if "一" <= ch <= "鿿" or ch.isalnum():
            kept.append(ch)
        else:
            kept.append(" ")
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def tokenize(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """(单字/拉丁词集合, 中文相邻 bigram 集合)。"""
    norm = normalize(text)
    unigrams = set(_LATIN_WORD.findall(norm))
    cjk = _CJK_CHAR.findall(norm)
    unigrams.update(cjk)
    bigrams = {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    return frozenset(unigrams), frozenset(bigrams)


def fingerprint(
    task: str,
    *,
    tag_lexicon: dict[str, tuple[str, ...]] | None = None,
) -> TaskFingerprint:
    """把任务文本转成稳定指纹。"""
    lexicon = tag_lexicon if tag_lexicon is not None else DEFAULT_TAG_LEXICON
    norm = normalize(task)

    unigrams, bigrams = tokenize(norm)

    # 能力标签：命中词子串即算命中（在归一文本上匹配，保证跨大小写/全角稳定）
    tags: list[str] = []
    for tag, words in lexicon.items():
        if any(normalize(w) and normalize(w) in norm for w in words):
            tags.append(tag)
    tags = tuple(sorted(set(tags)))

    # 结构信号
    signals: list[str] = []
    if any(w in norm for w in _MULTI_STEP):
        signals.append("multi_step")
    if any(w in norm for w in _ACTION):
        signals.append("action")
    if any(w in norm for w in _VAGUE):
        signals.append("vague")
    if any(w in norm for w in _QUESTION):
        signals.append("question")
    signals = tuple(sorted(set(signals)))

    # 稳定 key：只取内容相关字段，与词典配置无关（同一任务跨配置 key 不变）
    content = "|".join([norm, ",".join(tags), ",".join(signals)])
    key = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    return TaskFingerprint(
        original=task,
        normalized=norm,
        unigrams=tuple(sorted(unigrams)),
        bigrams=tuple(sorted(bigrams)),
        tags=tags,
        signals=signals,
        key=key,
    )
