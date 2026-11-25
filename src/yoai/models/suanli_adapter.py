"""算里（suanli.cn）OpenAI 兼容网关适配器 · L2 真接入。

环境来源（实测 2026-11-21，Core 的 .env）：
  OPENAI_BASE_URL = https://api.suanli.cn/v1
  OPENAI_API_KEY = <key>
  LLM_MODEL = deepseek/deepseek-v4.1-flash-1017
真实调用已验证 HTTP 200，返回标准 chat/completions 结构。
key 从 .env 读到内存后使用，不回显、不写日志、不进结果。
"""

from __future__ import annotations

import json
import os
import sys
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

def _default_core_env() -> Path:
    """定位 Core 的 .env：环境变量优先，其次按常见相对位置探测。

    - ``YAI_CORE_ENV``：直接指定 .env 文件；
    - ``YAI_CORE_SRC``：Core 源码根目录，取其中的 .env；
    - 本仓库父目录下的 ``YAI Agent Core`` / ``yai-agent-core``：取其中的 .env。

    都不存在时返回一个不存在的占位路径，``available()`` 会如实返回 False。
    """
    explicit = os.environ.get("YAI_CORE_ENV")
    if explicit:
        return Path(explicit).expanduser()
    core_src = os.environ.get("YAI_CORE_SRC")
    if core_src:
        return Path(core_src).expanduser() / ".env"

    # 从 sys.path 里已注入的 Core/src 反推根目录（src 的上一层）
    for entry in sys.path:
        if not entry:
            continue
        try:
            path = Path(entry)
        except OSError:
            continue
        if (path / "yai_core").is_dir():
            candidate = path.parent / ".env"
            if candidate.exists():
                return candidate

    here = Path(__file__).resolve()
    for parent in here.parents:
        for name in ("YAI Agent Core", "yai-agent-core", "yai_agent_core"):
            candidate = parent / name / ".env"
            if candidate.exists():
                return candidate
    return Path(".env")


DEFAULT_CORE_ENV = _default_core_env()


class SuanliAdapter(PeerAdapter):
    """走 OpenAI chat/completions 协议的算里网关。"""

    level = "L2"

    # 类级累计：所有实例共享（评测每题新建 adapter，进程级汇总用）。
    # 不影响任何答题行为，只做旁路统计。调用 reset_usage_stats() 可清零。
    usage_stats: dict[str, int] = {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "cached_tokens": 0, "reasoning_tokens": 0,
    }

    @classmethod
    def reset_usage_stats(cls) -> None:
        cls.usage_stats = {k: 0 for k in cls.usage_stats}

    @classmethod
    def add_usage(cls, usage: dict[str, Any]) -> None:
        if not isinstance(usage, dict):
            return
        cls.usage_stats["calls"] += 1
        for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                  "cached_tokens", "reasoning_tokens"):
            cls.usage_stats[k] += int(usage.get(k, 0) or 0)

    def __init__(
        self,
        name: str = "算里 DeepSeek",
        *,
        env_path: str | Path = DEFAULT_CORE_ENV,
        enabled: bool = True,
        timeout_s: float = 60.0,
        max_tokens: int | None = None,   # None=读 YOAI_MAX_TOKENS，默认 32000
        temperature: float | None = None,
        transport_retries: int = 2,
    ) -> None:
        super().__init__(name, enabled=enabled, timeout_s=timeout_s)
        self.env_path = Path(env_path)
        # max_tokens 是单次模型输出上限（含 tool_calls 的 arguments JSON）。
        # 默认 1024 会让"把整份源码写进 proj_write(content=...)"这类调用被截断：
        # JSON 参数没写完 → 解析成空 {} → 工具报"path/content 必填"（2026-11-25 实测）。
        # 默认 32000，可用 YOAI_MAX_TOKENS 覆盖。
        if max_tokens is None:
            try:
                self.max_tokens = int(os.environ.get("YOAI_MAX_TOKENS", "32000").strip())
            except ValueError:
                self.max_tokens = 32000
        else:
            self.max_tokens = max_tokens
        # None=不传该字段（保持网关默认与既有行为）；显式值用于稳定抽取实验。
        # AMBRACE extractor.py:582 用 temperature=0.1 做记忆抽取，借鉴此思路。
        self.temperature = temperature
        # 仅 transport 错误重试：网关负载高时连接超时是随机抖动（实测中午低价时段
        # 连1路都会偶发 transport 错误），重试可避免评测/生产丢那条记忆。
        # HTTP 错误（429/401/5xx）不重试，避免放大限流或配置问题。
        self.transport_retries = max(0, transport_retries)
        self.last_status = ""
        # 流式 outbox（2026-11-24）：OpenAI 兼容 SSE 增量暂存，
        # YoAiAgent.poller drain 成 delta 事件 → UI 逐字显示。
        # 网关不支持 stream 时设 YOAI_STREAM=0 回退一次性 post_json。
        self.stream = os.environ.get("YOAI_STREAM", "1") != "0"
        self.text_outbox: list[tuple[int, str]] = []
        self.thinking_outbox: list[str] = []
        self.stream_round = -1

    def _config(self) -> tuple[str, str, str]:
        env = read_env_file(self.env_path)
        # 环境变量覆盖：仅当显式设置时才生效，用于评测切换网关而不改桌面默认配置。
        # 三个变量必须同时设置才整体覆盖，避免只改了 key 却用旧 base_url 的错配。
        override = (
            os.environ.get("YOAI_BASE_URL"),
            os.environ.get("YOAI_API_KEY"),
            os.environ.get("YOAI_MODEL"),
        )
        if all(override):
            base, key, model = override
            return base.rstrip("/"), key, model
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
        if self.stream:
            return self._send_stream(base, key, payload)
        data = None
        http_error: ModelHTTPError | None = None
        transport_error: ModelTransportError | None = None
        for attempt in range(self.transport_retries + 1):
            try:
                data = post_json(
                    base + "/chat/completions", payload,
                    {"Authorization": "Bearer " + key}, self.timeout_s,
                )
                break   # 成功，跳出重试
            except ModelHTTPError as exc:
                http_error = exc   # HTTP 错误（429/401/5xx）不重试，避免放大限流/配置问题
                break
            except ModelTransportError as exc:
                transport_error = exc
                if attempt >= self.transport_retries:
                    break
                # 指数退避：0.5s / 1s / 2s…，避免给高负载网关雪上加霜
                import time as _time
                _time.sleep(0.5 * (2 ** attempt))
        if http_error is not None:
            self.last_status = f"http_{http_error.status}"
            return AdapterResult(False, level=self.level,
                                 detail=friendly_http_error(http_error.status, http_error.message),
                                 meta={"http_status": http_error.status})
        if data is None:
            self.last_status = "transport_error"
            detail = f"网关连接失败：{transport_error}" if transport_error else "网关连接失败"
            return AdapterResult(False, level=self.level, detail=detail + "（已重试）")

        text, usage = _extract_text(data)
        tool_calls = _extract_tool_calls(data)
        self.add_usage(usage)   # 旁路统计，不影响答题
        self.last_status = "ok"
        if not text and not tool_calls:
            return AdapterResult(False, level=self.level, detail="网关返回空文本", meta={"usage": usage})
        return AdapterResult(True, text=text, level=self.level, meta={"usage": usage},
                             tool_calls=tool_calls)


    def _send_stream(self, base: str, key: str, payload: dict[str, Any]) -> AdapterResult:
        """OpenAI 兼容 SSE 流式发送：增量推 outbox，聚合结果走既有提取逻辑。

        网关实测（讯飞 spark-x2.6）：思考模型的增量在 delta.reasoning_content，
        正式回答在 delta.content——两者都推（reasoning 进 thinking_outbox）。
        tool_calls 的 arguments 以 JSON 片段增量出现，按 index 聚合。
        """
        import json as _json
        import urllib.request as _urlreq

        self.stream_round += 1
        round_id = self.stream_round
        payload = {**payload, "stream": True}
        body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = _urlreq.Request(
            base + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "User-Agent": "YoAi/1.0",
                     "Authorization": "Bearer " + key},
            method="POST",
        )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        try:
            with _urlreq.urlopen(req, timeout=self.timeout_s) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                    except Exception:  # noqa: BLE001 - 坏块跳过，不能中断整轮
                        continue
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0] or {}).get("delta") or {}
                    text = delta.get("content") or ""
                    reasoning = delta.get("reasoning_content") or ""
                    if text:
                        content_parts.append(text)
                        self.text_outbox.append((round_id, text))
                    if reasoning:
                        reasoning_parts.append(reasoning)
                        self.thinking_outbox.append(reasoning)
                    for call in delta.get("tool_calls") or []:
                        idx = int(call.get("index", 0))
                        slot = tool_calls.setdefault(idx, {
                            "id": "", "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                        if call.get("id"):
                            slot["id"] = call["id"]
                        fn = call.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
        except ModelHTTPError as exc:
            self.last_status = f"http_{exc.status}"
            return AdapterResult(False, level=self.level,
                                 detail=friendly_http_error(exc.status, exc.message),
                                 meta={"http_status": exc.status})
        except (Exception,) as exc:  # noqa: BLE001 - 与 send 同步路径同语义（含 URLError/timeout）
            self.last_status = "transport_error"
            return AdapterResult(False, level=self.level,
                                 detail=f"网关连接失败：{type(exc).__name__}: {exc}（已重试）"
                                 if self.transport_retries else
                                 f"网关连接失败：{type(exc).__name__}: {exc}")

        # 聚合：content 缺失时用 reasoning_content（与非流式 _extract_text 同语义）
        full_text = "".join(content_parts).strip() or "".join(reasoning_parts).strip()
        calls = flatten_stream_tool_calls(tool_calls)
        usage_norm = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        self.add_usage(usage_norm)
        self.last_status = "ok"
        if not full_text and not calls:
            return AdapterResult(False, level=self.level, detail="网关返回空文本",
                                 meta={"usage": usage_norm})
        return AdapterResult(True, text=full_text, level=self.level,
                             meta={"usage": usage_norm}, tool_calls=calls)

    def drain_text(self) -> list[tuple[int, str]]:
        """取走并清空流式文本增量 [(round, delta), ...]（UI 逐字显示用）。"""
        items = list(self.text_outbox)
        self.text_outbox.clear()
        return items

    def drain_thinking(self) -> list[str]:
        """取走并清空流式思考增量（reasoning_content）。"""
        items = list(self.thinking_outbox)
        self.thinking_outbox.clear()
        return items


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
    # 缓存命中 token——降本分析的关键指标（命中价可差 50 倍）。
    # 兼容 OpenAI 标准 prompt_tokens_details，也兼容部分网关的 prompt_tokens_details.cached_tokens。
    if isinstance(usage_raw, dict):
        details = usage_raw.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            usage["cached_tokens"] = details.get("cached_tokens", 0)
        usage["reasoning_tokens"] = (
            (usage_raw.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            if isinstance(usage_raw.get("completion_tokens_details"), dict) else 0
        )
    return text.strip(), usage


def _repair_truncated_json(raw: str) -> dict[str, Any] | None:
    """尽力修复被 max_tokens 截断的 tool_calls arguments JSON。

    常见截断：字符串值写到一半断掉、缺结尾引号/括号。逐位回退补齐 " / } / ]，
    解析成功则返回 dict；实在救不回返回 None（由调用方带 _parse_error 明示）。
    """
    s = raw.strip()
    if not s.startswith("{"):
        return None
    candidates = [s]
    # 截断常见形态：缺右引号 / 缺右括号 / 两者都缺，以及尾部逗号
    for suffix in ('"', '}', '"]', '"}', '"}]', '}]', '",', '"}'):
        candidates.append(s + suffix)
    # 逐步去掉不完整的尾部键值片段再补括号
    for cut in range(1, min(40, len(s)) + 1):
        head = s[:-cut].rstrip().rstrip(",")
        for suffix in ('"', '"}', '}', '"}]', ']}'):
            candidates.append(head + suffix)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict) and parsed:
            # 空 dict 不算"修复成功"——那等于参数全丢，正是要避免的静默失败
            return parsed
    return None


def flatten_stream_tool_calls(raw_calls: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """流式 SSE 聚合结果与 GatewayModelProvider 期望对齐（扁平 name/arguments）。

    OpenAI 增量格式是 {"function":{"name":..,"arguments":"<json>"}}；
    GatewayModelProvider 读 tc["name"]/tc["arguments"]，不扁平化会被静默丢弃——
    这正是"模型决定调工具但工具从不执行"的根因。
    """
    out: list[dict[str, Any]] = []
    for idx in sorted(raw_calls):
        slot = raw_calls[idx]
        fn = slot.get("function") or {}
        arguments = fn.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (ValueError, TypeError):
                # 关键：不能静默变成 {}——那会让工具报"必填参数缺失"，
                # 模型误判为"参数注入问题"并放弃（2026-11-25 实测）。
                # 尽力修复被截断的 JSON（补引号/括号），实在不行把原始片段
                # 放进 _parse_error 让调用方/模型看到真实原因。
                repaired = _repair_truncated_json(arguments)
                if repaired is not None:
                    arguments = repaired
                else:
                    arguments = {"_parse_error": (
                        "tool_calls arguments JSON 解析失败（疑似 max_tokens 截断）："
                        f"{arguments[:120]!r}…（原始长度 {len(arguments)}）"
                    )}
        out.append({
            "id": str(slot.get("id", "")),
            "name": str(fn.get("name", "")),
            "arguments": arguments if isinstance(arguments, dict) else {},
        })
    return out


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
