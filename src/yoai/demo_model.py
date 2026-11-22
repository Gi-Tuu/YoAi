"""YoAi DemoModel — 离线可交互的 ModelProvider 实现。

定位：桌面 APP 在没有 API Key 时也能"真对话、真调工具、真落盘"，而不是
播完一段固定脚本就结束。它按用户输入的关键词识别意图，经 Core 的工具循环
完成任务。真实上线把它整体换成 OpenAICompatProvider 即可（见 README）。

注意：这是**演示模型**，意图识别用关键词匹配，不是 NLP/LLM。它的价值是
证明端到端链路（用户输入 → Core 决策 → 工具执行 → 状态落盘 → 回答）通畅。
"""

from __future__ import annotations

import re
from typing import Any

from yai_core.types import ModelResponse, ToolCallRequest


class DemoModel:
    """按关键词识别意图的离线演示模型（实现 ModelProvider 契约）。"""

    # 不声明 yai_live_router → llm_router="auto" 下走零网络规则路由。
    yai_multimodal = False

    def __init__(self, owner: str = "YoAi") -> None:
        # owner 用于群聊里区分不同智能体的自称（如"我是小策"）。
        self.owner = owner
        self._counter = 0

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        # 取最近一条 user 文本作为意图输入。
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                user_text = content if isinstance(content, str) else self._flatten(content)
                break

        # 已有工具结果 → 进入收尾：基于工具返回值给最终答复。
        if messages and messages[-1].get("role") == "tool":
            tool_content = str(messages[-1].get("content", ""))
            return ModelResponse(content=self._summarize(tool_content))

        # 否则按意图发起一次工具调用。
        tool_call = self._intent_to_tool(user_text)
        if tool_call is not None:
            self._counter += 1
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id=f"demo-{self._counter}",
                        name=tool_call[0],
                        arguments=tool_call[1],
                    )
                ],
            )

        return ModelResponse(content=self._chat(user_text))

    # --- 意图识别 ---
    def _intent_to_tool(self, text: str) -> tuple[str, dict[str, Any]] | None:
        # "记住我偏好X" / "记住我喜欢X" —— 没有"是/="分隔的自然句式
        m = re.search(r"记住(?:我)?(?:的)?(偏好|喜欢|名字|城市)\s*(.+)$", text)
        if m:
            return ("remember_fact", {"key": m.group(1),
                                      "value": m.group(2).strip("，。 "), "tag": "偏好"})
        # 记住偏好/事实：记住我偏好X是Y / 记住：X是Y
        m = re.search(r"记住(?:我|我的)?(?:偏好|喜欢|是)?\s*(.+?)\s*(?:是|为|=)\s*(.+)", text)
        if m:
            return ("remember_fact", {"key": m.group(1).strip(), "value": m.group(2).strip(),
                                      "tag": "偏好"})
        m = re.search(r"记住\s*[:：]?\s*(.+)$", text)
        if m and ("是" in m.group(1) or "=" in m.group(1)):
            parts = re.split(r"\s*(?:是|=)\s*", m.group(1), maxsplit=1)
            if len(parts) == 2:
                return ("remember_fact", {"key": parts[0].strip(), "value": parts[1].strip()})

        # 取回事实：我记得X吗 / X是什么 / 查一下X
        if re.search(r"(是什么|我记得|查一下|取回|回忆)", text) and "目标" not in text:
            key = self._extract_key(text, ("是什么", "我记得", "查一下", "取回", "回忆"))
            if key:
                return ("recall_fact", {"key": key})

        # 列出事实：我都记住了什么 / 列出事实 / 列偏好
        if re.search(r"(记住了什么|列出.*事实|我的偏好|有哪些事实|列.*偏好)", text):
            return ("list_facts", {})

        # 创建目标：目标/计划/要做 X
        if re.search(r"(目标|计划|要做|待办)", text) and re.search(r"(创建|新建|加|加个|设|定)", text):
            title = re.sub(r"(帮我|请)?(创建|新建|加个?|设定?|定个?)?一个?(长期)?(目标|计划|待办)?",
                           "", text).strip("：: ，,")
            return ("create_goal", {"title": title or text, "steps": []})

        # 列出目标：有哪些目标 / 目标列表 / 我的目标
        if re.search(r"(目标|计划)", text) and re.search(r"(有哪些|列表|列出|看看|我的|全部|进度)", text):
            return ("list_goals", {})

        return None

    def _extract_key(self, text: str, markers: tuple[str, ...]) -> str:
        for marker in markers:
            idx = text.find(marker)
            if idx < 0:
                continue
            # "X是什么" → 取 marker 前；"我记得X" → 取 marker 后
            if marker == "是什么":
                key = text[:idx]
            else:
                key = text[idx + len(marker):]
                key = key.strip("？?。 ，,什么我的")
                if key:
                    return key
        return ""

    def _flatten(self, content: Any) -> str:
        if isinstance(content, list):
            return " ".join(
                str(part.get("text", "")) for part in content
                if isinstance(part, dict)
            )
        return str(content)

    def _summarize(self, tool_content: str) -> str:
        raw = tool_content.strip()
        try:
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "result" in parsed:
                raw = str(parsed["result"])
        except (ValueError, TypeError):
            pass
        return f"已处理。结果：{raw[:400]}" if raw else "已完成。"

    def _chat(self, text: str) -> str:
        text = text.strip()
        if not text:
            return f"你好，我是{self.owner}。试试让我记住一件事，或创建/查看目标。"
        if any(w in text for w in ("你好", "hi", "hello", "嗨", "大家好")):
            return f"你好！我是{self.owner}，在群里和大家一起工作。我能记住偏好、管理目标。"
        return f"[{self.owner}] 收到「{text}」。我会处理这件事并同步结果。"
