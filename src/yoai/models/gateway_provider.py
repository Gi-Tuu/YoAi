"""GatewayModelProvider — 把真实模型适配器桥接成 Core 的 ModelProvider。

Core 契约：async achat(messages, tools, tier) -> ModelResponse。
适配器契约：send(message, *, tools, messages, system_prompt) -> AdapterResult。

两种模式（按适配器声明的 capabilities 自动判断）：
- 工具模式：适配器 capabilities 含 "tool_calls" → 透传完整 OpenAI messages + tools，
  把返回的 tool_calls 转成 Core 的 ToolCallRequest。Core 执行工具后把结果放回 messages，
  下一轮再调，形成完整工具循环。
- 纯文本模式：旧适配器/简单网关 → 渲染成文本 prompt，只返回 content（无工具调用）。

usage 如实透传（拿不到就 None）；同步 HTTP 放 asyncio.to_thread 不阻塞事件循环。
"""

from __future__ import annotations

import asyncio
from typing import Any

from yai_core.types import ModelResponse, TokenUsage, ToolCallRequest

from yoai.adapters.base import PeerAdapter
from yoai.models.stall import STALL_NUDGE, is_stall_text


class GatewayModelProvider:
    """把 PeerAdapter 包装成 Core ModelProvider（工具模式优先，纯文本降级）。"""

    yai_multimodal = False   # 纯文本接口，不声明多模态

    def __init__(self, adapter: PeerAdapter, *, include_system: bool = True,
                 reask_on_stall: bool = True) -> None:
        self.adapter = adapter
        self.include_system = include_system
        self.reask_on_stall = bool(reask_on_stall)
        self.calls = 0
        self.tool_mode = "tool_calls" in adapter.capabilities()
        # 真实 token 用量累计：Core 的 DONE 只在配置 Budget 时带 usage，
        # 未配置时宿主可从这里读（来自真实 ModelResponse.usage，不臆造）。
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def accumulate_usage(self, usage: TokenUsage | None) -> None:
        if usage is None:
            return
        self.total_usage["prompt_tokens"] += usage.prompt_tokens
        self.total_usage["completion_tokens"] += usage.completion_tokens
        self.total_usage["total_tokens"] += usage.total_tokens

    async def _ask_once(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[ModelResponse, bool]:
        """发一次请求。返回 (响应, 网关是否出错)。"""
        self.calls += 1
        if self.tool_mode:
            # 工具模式：透传完整对话与工具 schema，保留 tool 结果轮次
            result = await asyncio.to_thread(
                self.adapter.send, "", tools=tools, messages=messages,
            )
        else:
            prompt = self._render(messages)
            result = await asyncio.to_thread(self.adapter.send, prompt)

        usage: TokenUsage | None = None
        raw_usage = result.meta.get("usage") if isinstance(result.meta, dict) else None
        if isinstance(raw_usage, dict) and raw_usage:
            usage = TokenUsage(
                prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                total_tokens=int(raw_usage.get("total_tokens", 0)),
            )
        self.accumulate_usage(usage)

        if not result.ok:
            return ModelResponse(content=f"[模型网关错误] {result.detail}", usage=usage), True

        tool_calls = [
            ToolCallRequest(
                id=str(tc.get("id", "")),
                name=str(tc.get("name", "")),
                arguments=tc.get("arguments", {}) if isinstance(tc.get("arguments"), dict) else {},
            )
            for tc in result.tool_calls
            if isinstance(tc, dict) and tc.get("name")
        ]
        return ModelResponse(content=result.text, tool_calls=tool_calls, usage=usage), False

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        response, failed = await self._ask_once(messages, tools)
        if failed or not self.reask_on_stall or not tools or response.tool_calls:
            return response

        # 纯文本 + 有工具 + 是"我去查一下"这类过渡语 → Core 会当最终答案结束，
        # 任务还没执行。追加一次明确指令重试（最多一次，防循环）。
        if not is_stall_text(response.content or ""):
            return response
        nudge_messages = list(messages) + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": STALL_NUDGE},
        ]
        retried, failed2 = await self._ask_once(nudge_messages, tools)
        # 重试仍失败/仍是过渡语 → 返回原响应，不无限纠缠
        if failed2 or (not retried.tool_calls
                       and is_stall_text(retried.content or "")):
            return response
        return retried

    def _render(self, messages: list[dict[str, Any]]) -> str:
        """纯文本降级：把 OpenAI 线格式消息渲染成文本 prompt。"""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(p.get("text", "")) for p in content
                    if isinstance(p, dict)
                )
            if not isinstance(content, str) or not content.strip():
                continue
            if role == "system" and not self.include_system:
                continue
            label = {"system": "系统", "user": "用户", "assistant": "助手"}.get(role, role)
            parts.append(f"[{label}] {content.strip()}")
        return "\n".join(parts) if parts else "你好"

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.adapter.name,
            "level": self.adapter.level,
            "mode": "tool_calls" if self.tool_mode else "text_only",
            "tool_calls": self.tool_mode,
        }
