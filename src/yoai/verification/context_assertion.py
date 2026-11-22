"""YoAi 个人事实的状态断言 —— 验收"记住 X"类任务的副作用是否真的落盘。

设计原则：查真实 PersonalContext 状态，不看模型自评、不看工具回执文本。

策略（宽松匹配，容忍模型改写 key）：
- 从目标文本里找"记住/记下/保存"等意图；
- 提取引号内的值或"是/为/叫"后面的值；
- 查 context.list_all() 的 value 是否包含该值 → verified_success；
- 有记忆意图但找不到对应落盘 → verified_failure（硬证据：状态没达成）；
- 目标无可验证的记忆意图 → not_verifiable（不假装验收）。

这是 StateAssertionVerifier 的 assertion 工厂：assertion = make_context_assertion(context)
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from yai_core.types import Evidence

from yoai.verification.verifiers import _REMEMBER_WORDS

# 从"记住：我的城市是杭州"/"记住 X 叫 Y"/"记住「偏好」为深色"里抽 value
_VALUE_PATTERNS = (
    r"[是为叫]\s*([^\s，,。；;]{1,30})",
    r"[「\"']([^」\"']{1,30})[」\"']",
    r"[:：]\s*([^\s，,。；;]{1,30})",
)


def make_context_assertion(context: Any):
    """构造一个查询真实 context 状态的断言函数。"""
    def assertion(
        goal: str,
        evidence: Sequence[Evidence],
        metadata: Mapping[str, Any],
    ) -> tuple[str, str, float]:
        if not any(w in goal for w in _REMEMBER_WORDS):
            return ("not_verifiable", "目标无可硬验证的记忆意图，状态断言跳过", 0.0)

        facts = context.list_all() if hasattr(context, "list_all") else {}
        if not isinstance(facts, dict):
            return ("not_verifiable", "个人事实状态不可读", 0.0)

        values = [str(v) for v in facts.values()]
        goal_clean = goal.strip()
        candidates: list[str] = []
        for pattern in _VALUE_PATTERNS:
            candidates.extend(re.findall(pattern, goal_clean))
        candidates = [c.strip("。；;，, ") for c in candidates if c.strip()]

        if not candidates:
            # 无法从目标抽出具体值 → 不硬判失败（可能模型自由发挥），诚实跳过
            return ("not_verifiable", "无法从目标提取可核对的具体值", 0.0)

        # 任一候选值真实落在 facts 的 value 中 → 状态达成
        for c in candidates:
            if any(c in v or v in c for v in values if v):
                return (
                    "verified_success",
                    f"状态断言通过：值「{c}」已真实存在于个人事实（共 {len(facts)} 条）",
                    0.95,
                )
        preview = "、".join(values[:5]) if values else "（空）"
        return (
            "verified_failure",
            f"状态断言失败：目标值 {candidates[:3]} 未出现在真实个人事实中（现有：{preview}）",
            0.9,
        )

    return assertion
