"""DeepSeek Anthropic 兼容网关适配器 · L2 真接入。

环境来源（实测 2026-11-21）：
  ANTHROPIC_BASE_URL = https://api.deepseek.com/anthropic
  ANTHROPIC_AUTH_TOKEN = <key>
  ANTHROPIC_MODEL = deepseek-flash[1m]
真实调用已验证 HTTP 200，返回 content 块数组（thinking + text），取 text 块。
key 只在内存使用，不回显、不写盘。
"""

from __future__ import annotations

import os
from typing import Any

from yoai.adapters.base import AdapterResult, PeerAdapter
from yoai.models.http_base import (
    ModelHTTPError,
    ModelTransportError,
    friendly_http_error,
    post_json,
)


class DeepSeekAnthropicAdapter(PeerAdapter):
    """走 Anthropic messages 协议的 DeepSeek 网关。"""

    level = "L2"

    def __init__(
        self,
        name: str = "DeepSeek (Anthropic)",
        *,
        enabled: bool = True,
        timeout_s: float = 60.0,
        max_tokens: int = 1024,
    ) -> None:
        super().__init__(name, enabled=enabled, timeout_s=timeout_s)
        self.max_tokens = max_tokens
        self.last_status = ""

    def _config(self) -> tuple[str, str, str]:
        base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
        key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        model = os.environ.get("ANTHROPIC_MODEL", "")
        return base, key, model

    def available(self) -> bool:
        if not self.enabled:
            return False
        base, key, model = self._config()
        return bool(base and key and model)

    def capabilities(self) -> list[str]:
        return ["chat", "auto_reply", "anthropic_compat", "usage", "tool_calls"]

    def send(
        self,
        message: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
        system_prompt: str = "",
    ) -> AdapterResult:
        """发送。OpenAI 形状的 tools/messages 会被转成 Anthropic 协议。

        Anthropic 差异：system 走顶层字段；tool 结果作为 user 的 tool_result 块；
        assistant 的 tool_calls 作为 assistant 的 tool_use 块。
        """
        if not self.enabled:
            return AdapterResult(False, level=self.level, detail="适配器已禁用")
        base, key, model = self._config()
        if not (base and key and model):
            return AdapterResult(False, level=self.level,
                                 detail="缺少 ANTHROPIC_BASE_URL / AUTH_TOKEN / MODEL 环境变量")
        anthropic_messages = (
            _openai_messages_to_anthropic(messages) if messages is not None
            else [{"role": "user", "content": message}]
        )
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": anthropic_messages,
        }
        system_text = system_prompt or _pull_system(messages)
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = [_openai_tool_to_anthropic(t) for t in tools]
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        try:
            data = post_json(base + "/v1/messages", payload, headers, self.timeout_s)
        except ModelHTTPError as exc:
            self.last_status = f"http_{exc.status}"
            return AdapterResult(False, level=self.level,
                                 detail=friendly_http_error(exc.status, exc.message),
                                 meta={"http_status": exc.status})
        except ModelTransportError as exc:
            self.last_status = "transport_error"
            return AdapterResult(False, level=self.level, detail=f"网关连接失败：{exc}")

        text, usage = _extract_text(data)
        tool_calls = _extract_tool_calls(data)
        self.last_status = "ok"
        if not text and not tool_calls:
            return AdapterResult(False, level=self.level, detail="网关返回空文本", meta={"usage": usage})
        return AdapterResult(True, text=text, level=self.level, meta={"usage": usage},
                             tool_calls=tool_calls)


def _pull_system(messages: list[dict[str, Any]] | None) -> str:
    """把 OpenAI messages 里的 system 内容合并成 Anthropic 顶层 system。"""
    if not messages:
        return ""
    parts: list[str] = []
    for m in messages:
        if m.get("role") != "system":
            continue
        c = m.get("content", "")
        if isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


def _openai_messages_to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI 线格式 → Anthropic messages。

    直接委托 Core 官方实现 `yai_core.llm.anthropic.to_anthropic_messages`——
    它已正确处理两条硬约束：工具结果挂 user 消息、相邻同角色合并
    （一次多工具调用的多个 tool_result 必须合成一条 user，否则网关 400）。

    2026-11-24 曾在此自写转换（漏了合并→生产 400），发现 Core 早有正确实现后改为委托，
    避免重复造轮子、跟随 Core 维护。
    """
    from yai_core.llm.anthropic import to_anthropic_messages
    # Core 实现：system 消息会被转成 _content_blocks 而不是丢掉——
    # 但 Anthropic 要求 system 走顶层字段，由 send() 的 _pull_system 处理，这里过滤掉。
    without_system = [m for m in messages if m.get("role") != "system"]
    return to_anthropic_messages(without_system)


def _openai_tool_to_anthropic(tool: dict[str, Any]) -> dict[str, Any]:
    """OpenAI function 工具 → Anthropic tool（input_schema 来自 function.parameters）。"""
    fn = tool.get("function", {}) if isinstance(tool, dict) else {}
    if not isinstance(fn, dict):
        fn = {}
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _extract_tool_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
    """从 Anthropic 响应的 tool_use 块解析工具调用。"""
    out: list[dict[str, Any]] = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            out.append({
                "id": str(block.get("id", "")),
                "name": str(block.get("name", "")),
                "arguments": block.get("input", {}) if isinstance(block.get("input"), dict) else {},
            })
    return out


def _extract_text(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """从 Anthropic messages 响应取 text 块（跳过 thinking），并提取 usage。"""
    parts: list[str] = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    usage_raw = data.get("usage", {})
    usage = {
        "prompt_tokens": usage_raw.get("input_tokens", 0),
        "completion_tokens": usage_raw.get("output_tokens", 0),
        "total_tokens": usage_raw.get("input_tokens", 0) + usage_raw.get("output_tokens", 0),
    } if isinstance(usage_raw, dict) else {}
    return "".join(parts).strip(), usage
