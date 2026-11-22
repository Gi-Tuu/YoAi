"""算里（suanli.cn）OpenAI 兼容网关适配器 · L2 真接入。

环境来源（实测 2026-11-21，Core 的 .env）：
  OPENAI_BASE_URL = https://api.suanli.cn/v1
  OPENAI_API_KEY = <key>
  LLM_MODEL = deepseek/deepseek-v4.1-flash-1017
真实调用已验证 HTTP 200，返回标准 chat/completions 结构。
key 从 .env 读到内存后使用，不回显、不写日志、不进结果。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoai.adapters.base import AdapterResult, PeerAdapter
from yoai.models.http_base import (
    ModelHTTPError,
    ModelTransportError,
    friendly_http_error,
    post_json,
    read_env_file,
)

DEFAULT_CORE_ENV = Path(r"E:\Competition\YAI Agent Core\.env")


class SuanliAdapter(PeerAdapter):
    """走 OpenAI chat/completions 协议的算里网关。"""

    level = "L2"

    def __init__(
        self,
        name: str = "算里 DeepSeek",
        *,
        env_path: str | Path = DEFAULT_CORE_ENV,
        enabled: bool = True,
        timeout_s: float = 60.0,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> None:
        super().__init__(name, enabled=enabled, timeout_s=timeout_s)
        self.env_path = Path(env_path)
        self.max_tokens = max_tokens
        # None=不传该字段（保持网关默认与既有行为）；显式值用于稳定抽取实验。
        # AMBRACE extractor.py:582 用 temperature=0.1 做记忆抽取，借鉴此思路。
        self.temperature = temperature
        self.last_status = ""

    def _config(self) -> tuple[str, str, str]:
        env = read_env_file(self.env_path)
        return (
            env.get("OPENAI_BASE_URL", "").rstrip("/"),
            env.get("OPENAI_API_KEY", ""),
            env.get("LLM_MODEL", ""),
        )

    def available(self) -> bool:
        if not self.enabled:
            return False
        base, key, model = self._config()
        return bool(base and key and model)

    def capabilities(self) -> list[str]:
        return ["chat", "auto_reply", "openai_compat", "usage", "tool_calls"]

    def send(
        self,
        message: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> AdapterResult:
        """发送。tools 为 OpenAI 形状工具 schema；messages 为完整对话（含 tool 结果）。

        messages 优先于 message —— Core 的工具循环会把 tool 结果放进历史，
        必须原样透传，模型才能基于工具结果给最终答案。
        """
        if not self.enabled:
            return AdapterResult(False, level=self.level, detail="适配器已禁用")
        base, key, model = self._config()
        if not (base and key and model):
            return AdapterResult(False, level=self.level,
                                 detail="缺少 OPENAI_BASE_URL / API_KEY / LLM_MODEL 配置")
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages if messages is not None else [{"role": "user", "content": message}],
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            data = post_json(
                base + "/chat/completions", payload,
                {"Authorization": "Bearer " + key}, self.timeout_s,
            )
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


def _extract_text(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    choices = data.get("choices", [])
    text = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content", "")
            text = content if isinstance(content, str) else ""
            if not text.strip():
                # 思考模型（deepseek-v4.1-flash 等）有时把 content 留成 None，
                # 把最终回答写进 reasoning_content。此时若直接判"空文本"会白丢一轮。
                # 仅在正式 content 缺失时降级到 reasoning，有 content 绝不取思考过程。
                reasoning = msg.get("reasoning_content", "")
                if isinstance(reasoning, str) and reasoning.strip():
                    text = reasoning.strip()
    usage_raw = data.get("usage", {})
    usage = {
        "prompt_tokens": usage_raw.get("prompt_tokens", 0),
        "completion_tokens": usage_raw.get("completion_tokens", 0),
        "total_tokens": usage_raw.get("total_tokens", 0),
    } if isinstance(usage_raw, dict) else {}
    return text.strip(), usage


def _extract_tool_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
    """从 OpenAI chat/completions 响应解析 tool_calls。arguments 是 JSON 字符串。"""
    out: list[dict[str, Any]] = []
    choices = data.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return out
    msg = choices[0].get("message", {})
    if not isinstance(msg, dict):
        return out
    for call in msg.get("tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function", {})
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        args = fn.get("arguments", "{}")
        if isinstance(args, str):
            import json
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                args = {}
        if not isinstance(args, dict):
            args = {}
        out.append({
            "id": str(call.get("id", "")),
            "name": str(fn["name"]),
            "arguments": args,
        })
    return out
