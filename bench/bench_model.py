"""评测专用 ModelProvider：绕开思考模型 content 为空的问题，且不传工具 schema。

LongMemEval 是纯记忆 QA，不需要工具；传工具会让 deepseek 偶发返回未识别的工具调用文本。
本 Provider 直接走 OpenAI 兼容网关：
- tool_mode=False（Core 不注入工具 schema）；
- content 为空时回退 reasoning_content（deepseek 思考模型特性）；
- usage 真实透传。

不修改 src/yoai 任何代码，仅用于 bench/。
"""

from __future__ import annotations

import os

import asyncio
from pathlib import Path
from typing import Any

from yai_core.spi.model import ModelProvider
from yai_core.types import ModelResponse, TokenUsage

from yoai.models.http_base import read_env_file, post_json

def _core_env():
    explicit = os.environ.get("YAI_CORE_ENV")
    if explicit:
        return Path(explicit).expanduser()
    src = os.environ.get("YAI_CORE_SRC")
    if src:
        return Path(src).expanduser() / ".env"
    return Path(__file__).resolve().parents[2] / ".env"


CORE_ENV = _core_env()
MODEL = "deepseek/deepseek-v4.1-flash-1017"


class BenchModelProvider(ModelProvider):
    def __init__(self) -> None:
        env = read_env_file(CORE_ENV)
        self.base = env.get("OPENAI_BASE_URL", "").rstrip("/")
        self.key = env.get("OPENAI_API_KEY", "")
        self.total_usage: dict[str, int] = {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }
        self.calls = 0

    _NO_TOOL_HINT = (
        "You are answering a question using only the conversation history above. "
        "Answer with the final answer text directly. Do NOT output any tool calls, "
        "XML tags, <tool_call> markers, or commentary about tools."
    )

    def _render(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        """保留原始 role 结构；之前把所有消息拼成一个 user 串，模型会模仿历史里的
        XML 标记输出伪 <tool_call>，被 Core 的协议守卫 fail-closed 拒绝。"""
        out: list[dict[str, str]] = []
        for m in messages:
            role = m.get("role")
            content = str(m.get("content", ""))
            if role in ("system", "user", "assistant"):
                out.append({"role": role, "content": content})
        # 末尾追加一条明确指令，压住模型模仿历史标记/思考外泄的倾向
        if not any(m["role"] == "system" and self._NO_TOOL_HINT in m["content"] for m in out):
            out.append({"role": "system", "content": self._NO_TOOL_HINT})
        return out

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        self.calls += 1
        payload: dict[str, Any] = {
            "model": MODEL,
            # 保留 role 结构的消息列表（system/user/assistant 各归其位）
            "messages": self._render(messages),
            "max_tokens": 1024,   # deepseek 思考模型需足够 token 才输出 content（512 实测被截断）
        }
        # 明确不传 tools：纯记忆 QA 不需要工具
        data = await asyncio.to_thread(
            post_json,
            self.base + "/chat/completions",
            payload,
            {"Authorization": "Bearer " + self.key},
            90.0,
        )
        choices = data.get("choices", [])
        msg = choices[0].get("message", {}) if choices else {}
        content = msg.get("content", "")
        text = content.strip() if isinstance(content, str) else ""
        if not text:
            reasoning = msg.get("reasoning_content", "")
            text = reasoning.strip() if isinstance(reasoning, str) else ""
        raw_usage = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
            completion_tokens=int(raw_usage.get("completion_tokens", 0)),
            total_tokens=int(raw_usage.get("total_tokens", 0)),
        )
        for k, v in (("prompt_tokens", usage.prompt_tokens),
                     ("completion_tokens", usage.completion_tokens),
                     ("total_tokens", usage.total_tokens)):
            self.total_usage[k] += v
        return ModelResponse(content=text, usage=usage)
