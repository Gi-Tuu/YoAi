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


def _block_dict(block: Any) -> dict[str, Any]:
    """SDK 块对象 → dict（model_dump / __dict__ 兜底，对齐 Core _raw_block_dict）。"""
    if block is None:
        return {}
    if isinstance(block, dict):
        return dict(block)
    dump = getattr(block, "model_dump", None)
    if callable(dump):
        try:
            data = dump()
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001
            pass
    data = getattr(block, "__dict__", None)
    return ({k: v for k, v in data.items() if not k.startswith("_")}
            if isinstance(data, dict) else {})


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
        # thinking 事件 outbox（2026-11-24）：Core 把 thinking 块存进历史但**不发事件**，
        # UI 拿不到。这里在包装层拦截、暂存文本，由 YoAiAgent.astream drain 成事件。
        # 不改 Core 源码，跟随上游更新无忧。
        self.thinking_outbox: list[str] = []
        # 流式文本 outbox（2026-11-24）：SDK stream=True 每块增量文本暂存，
        # YoAiAgent.astream drain 成 delta 事件 → UI 逐字显示（每轮都流式）。
        # 元素 (round, delta)，round 从 0 递增，供 UI 区分多轮工具调用。
        self.text_outbox: list[tuple[int, str]] = []
        self.stream_round = -1
        # 默认开启流式；网关不支持 stream 时自动降级一次性返回（对齐既有语义）。
        self.stream = os.environ.get("YOAI_STREAM", "1") != "0"

    def accumulate_usage(self, usage: TokenUsage | None) -> None:
        if usage is None:
            return
        self.total_usage["prompt_tokens"] += usage.prompt_tokens
        self.total_usage["completion_tokens"] += usage.completion_tokens
        self.total_usage["total_tokens"] += usage.total_tokens

    def _stream_kwargs(self, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]] | None, tier: str) -> dict[str, Any]:
        """复用 Core 公开函数组装请求（协议跟随上游，不在 YoAi 重造翻译逻辑）。"""
        from yai_core.llm.anthropic import (
            split_system, to_anthropic_messages, to_anthropic_tools,
        )

        inner = self._inner
        system, rest = split_system(messages)
        kwargs: dict[str, Any] = {
            "model": inner.strong_model if tier == "strong" else inner.model,
            "messages": to_anthropic_messages(rest) or [
                {"role": "user", "content": [{"type": "text", "text": ""}]}
            ],
            "max_tokens": inner.max_tokens,
        }
        if system:
            if inner.prompt_cache:
                kwargs["system"] = [{
                    "type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                kwargs["system"] = system
        converted = to_anthropic_tools(tools) if tools else []
        if converted:
            if inner.prompt_cache:
                converted[-1] = {**converted[-1],
                                 "cache_control": {"type": "ephemeral"}}
            kwargs["tools"] = converted
        return kwargs

    async def _achat_stream(self, messages: list[dict[str, Any]],
                            tools: list[dict[str, Any]] | None,
                            tier: str, round_id: int) -> ModelResponse:
        """SDK 流式调用：增量文本推 outbox；最终聚合结果交 Core parse_response。"""
        from types import SimpleNamespace

        from yai_core.llm.anthropic import parse_response

        blocks: list[dict[str, Any]] = []   # 聚合 SDK 内容块（含 index）
        usage: dict[str, int] = {}
        async with self._inner.client.messages.stream(
            **self._stream_kwargs(messages, tools, tier)
        ) as stream:
            async for event in stream:
                kind = getattr(event, "type", "")
                if kind == "content_block_start":
                    idx = int(getattr(event, "index", 0))
                    block = getattr(event, "content_block", None)
                    data = _block_dict(block)
                    data.setdefault("index", idx)
                    while len(blocks) <= idx:
                        blocks.append({"index": len(blocks), "type": "text", "text": ""})
                    blocks[idx] = data
                    # thinking 块起始文本（有的网关在 start 里就带）
                    if data.get("type") in ("thinking", "redacted_thinking"):
                        text = str(data.get("thinking") or data.get("text") or "")
                        if text:
                            self.thinking_outbox.append(text)
                elif kind == "content_block_delta":
                    idx = int(getattr(event, "index", 0))
                    delta = getattr(event, "delta", None)
                    d = _block_dict(delta) or {}
                    while len(blocks) <= idx:
                        blocks.append({"index": len(blocks), "type": "text", "text": ""})
                    dt = d.get("text") or d.get("thinking") or d.get("partial_json") or ""
                    if d.get("type") == "input_json_delta" or "partial_json" in d:
                        blocks[idx]["input_json"] = blocks[idx].get("input_json", "") + dt
                    elif d.get("type") == "thinking_delta" or "thinking" in d:
                        blocks[idx]["thinking"] = blocks[idx].get("thinking", "") + dt
                        if dt:
                            self.thinking_outbox.append(dt)
                    elif dt:
                        blocks[idx]["text"] = blocks[idx].get("text", "") + dt
                        self.text_outbox.append((round_id, dt))   # UI 逐字显示
                elif kind == "content_block_stop":
                    idx = int(getattr(event, "index", 0))
                    if idx < len(blocks) and "input_json" in blocks[idx]:
                        import json
                        try:
                            blocks[idx]["input"] = json.loads(blocks[idx]["input_json"])
                        except Exception:  # noqa: BLE001
                            blocks[idx]["input"] = {}
                elif kind == "message_delta":
                    raw_usage = getattr(event, "usage", None)
                    if raw_usage is not None:
                        usage = {
                            "input_tokens": int(getattr(raw_usage, "input_tokens", 0) or 0),
                            "output_tokens": int(getattr(raw_usage, "output_tokens", 0) or 0),
                        }
        # 聚合块喂 Core 官方解析器（thinking/tool_use/usage 全跟随上游）
        final = SimpleNamespace(
            content=[{k: v for k, v in b.items() if k != "index"} for b in blocks],
            usage=SimpleNamespace(**usage) if usage else None,
        )
        return parse_response(final)

    async def achat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        tier: str = "standard",
    ) -> ModelResponse:
        self.calls += 1
        call = self._achat_stream if self.stream else None
        try:
            if call is not None:
                self.stream_round += 1
                response = await call(messages, tools, tier, self.stream_round)
            else:
                response = await self._inner.achat(messages, tools, tier=tier)
        except Exception as exc:  # noqa: BLE001 - 与 GatewayModelProvider 同语义：转文本不抛
            self.last_status = f"error:{type(exc).__name__}"
            return ModelResponse(content=f"[模型网关错误] {exc}")
        self.last_status = "ok"
        self.accumulate_usage(response.usage)
        self._capture_thinking(response)

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
            if call is not None:
                self.stream_round += 1
                retried = await call(nudge_messages, tools, tier, self.stream_round)
            else:
                retried = await self._inner.achat(nudge_messages, tools, tier=tier)
        except Exception:  # noqa: BLE001 - 重试失败 → 返回原响应，不无限纠缠
            return response
        self.accumulate_usage(retried.usage)
        self._capture_thinking(retried)
        if not retried.tool_calls and is_stall_text(retried.content or ""):
            return response
        return retried

    def _capture_thinking(self, response: ModelResponse) -> None:
        """从 Core 原生块里提取 thinking 文本到 outbox（不动 raw_content_blocks，
        回传仍由 Core 负责；signature 块无文本，不展示）。"""
        blocks = getattr(response, "raw_content_blocks", None) or []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") not in ("thinking", "redacted_thinking"):
                continue
            text = str(block.get("thinking") or block.get("text") or "").strip()
            if text:
                self.thinking_outbox.append(text)

    def drain_thinking(self) -> list[str]:
        """取走并清空本轮攒下的 thinking 文本（YoAiAgent 每轮事件循环调用）。"""
        items = list(self.thinking_outbox)
        self.thinking_outbox.clear()
        return items

    def drain_text(self) -> list[tuple[int, str]]:
        """取走并清空流式文本增量 [(round, delta), ...]（UI 逐字显示用）。"""
        items = list(self.text_outbox)
        self.text_outbox.clear()
        return items

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "level": "L2",
            "mode": "core_anthropic",
            "backend": "yai_core.llm.anthropic.AnthropicProvider",
        }
