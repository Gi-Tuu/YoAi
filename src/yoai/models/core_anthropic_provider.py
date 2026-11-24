"""CoreAnthropicModelProvider — 用 Core 官方 AnthropicProvider 作主对话模型。

2026-11-24 迁移：DeepSeek Anthropic 网关的主对话路径从自写
DeepSeekAnthropicAdapter + GatewayModelProvider 切到 Core 官方
``yai_core.llm.anthropic.AnthropicProvider``（协议翻译、prompt cache、
多模态、thinking 块回传都由 Core 维护，跟随上游更新）。

保留范围约定：
- **peer 聊天仍走 DeepSeekAnthropicAdapter**（ExternalPeer 依赖同步 send +
  AdapterResult 吞异常的语义，迁移需 asyncio 桥接且零收益）；
- SuanliAdapter（OpenAI 兼容网关）不适用 Anthropic 协议，维持原样。

包装两件 YoAi 生产需要、Core 不管的事：

1. **异常转友好错误**：Core kernel/loop 对 achat 异常 raise 不吞，SDK 异常会
   直冲 UI；这里转成 ``[模型网关错误]...`` 文本（对齐 GatewayModelProvider
   语义，模型下一轮看到错误可自愈或告知用户）。
2. **stall 过渡语重试**：模型只说"我去查一下"不调工具时追加一次明确指令
   （2026-11-24 真实生产修复，逻辑见 yoai.models.stall，不能丢）。

环境变量（与旧 adapter 完全一致，迁移无配置变化）：
  ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN（或 ANTHROPIC_API_KEY）/ ANTHROPIC_MODEL
  ANTHROPIC_MAX_TOKENS（可选，默认 4096）
  YOAI_ANTHROPIC_PROMPT_CACHE=1（可选，开启 cache_control；默认关——
  DeepSeek 网关对块状 system + cache_control 的兼容性未实测，先保守）
"""

from __future__ import annotations

import os
from typing import Any

from yai_core.types import ModelResponse, TokenUsage

from yoai.models.stall import STALL_NUDGE, is_stall_text


def core_anthropic_available() -> bool:
    """与旧 adapter 同一判据：三个环境变量齐备才可用。"""
    base = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    key = (os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
           or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    return bool(base and key and model)


class CoreAnthropicModelProvider:
    """Core 官方 AnthropicProvider 的 YoAi 生产包装（异常降级 + stall 重试）。"""

    yai_multimodal = True   # Core 官方后端支持 text/image 块

    def __init__(self, name: str = "DeepSeek (Anthropic · Core)") -> None:
        from yai_core.llm.anthropic import AnthropicProvider

        self.name = name
        base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
        key = (os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
               or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        model = os.environ.get("ANTHROPIC_MODEL", "").strip() or None
        # prompt_cache 默认关：块状 system + cache_control 在 DeepSeek 网关
        # 未实测；环境变量 YOAI_ANTHROPIC_PROMPT_CACHE=1 显式开启。
        prompt_cache = os.environ.get("YOAI_ANTHROPIC_PROMPT_CACHE", "") == "1"
        self._inner = AnthropicProvider(
            api_key=key,
            base_url=base or None,
            model=model,
            prompt_cache=prompt_cache,
        )
        self.calls = 0
        self.last_status = ""
        # 真实 token 用量累计（对齐 GatewayModelProvider.total_usage 的宿主约定）
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def accumulate_usage(self, usage: TokenUsage | None) -> None:
        if usage is None:
            return
        self.total_usage["prompt_tokens"] += usage.prompt_tokens
        self.total_usage["completion_tokens"] += usage.completion_tokens
        self.total_usage["total_tokens"] += usage.total_tokens

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        self.calls += 1
        try:
            response = await self._inner.achat(messages, tools, tier=tier)
        except Exception as exc:  # noqa: BLE001 - 与 GatewayModelProvider 同语义：转文本不抛
            self.last_status = f"error:{type(exc).__name__}"
            return ModelResponse(content=f"[模型网关错误] {exc}")
        self.last_status = "ok"
        self.accumulate_usage(response.usage)

        if response.tool_calls or not tools or not is_stall_text(response.content or ""):
            return response

        # 有工具可用但只回了"我去查一下"这类过渡语 → Core 会当最终答案结束，
        # 任务还没执行。追加一次明确指令重试（最多一次，防循环）。
        nudge_messages = list(messages) + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": STALL_NUDGE},
        ]
        self.calls += 1
        try:
            retried = await self._inner.achat(nudge_messages, tools, tier=tier)
        except Exception:  # noqa: BLE001 - 重试失败 → 返回原响应，不无限纠缠
            return response
        self.accumulate_usage(retried.usage)
        if not retried.tool_calls and is_stall_text(retried.content or ""):
            return response
        return retried

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "level": "L2",
            "mode": "core_anthropic",
            "backend": "yai_core.llm.anthropic.AnthropicProvider",
        }
