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
    """OpenAI 线格式 → Anthropic messages（system 移走；tool 结果变 user 块）。"""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "")
        if role == "system":
            continue
        if role == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": str(m.get("content", "")),
                }],
            })
            continue
        if role == "assistant" and m.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            content = m.get("content", "")
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            for call in m["tool_calls"]:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function", {})
                args = fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except (ValueError, TypeError):
                        args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": call.get("id", ""),
                    "name": fn.get("name", "") if isinstance(fn, dict) else "",
                    "input": args if isinstance(args, dict) else {},
                })
            out.append({"role": "assistant", "content": blocks})
            continue
        # user / 普通 assistant：content 数组降级为文本
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text", "")) for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        out.append({"role": role if role in ("user", "assistant") else "user",
                    "content": content if isinstance(content, str) else ""})
    return out


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
