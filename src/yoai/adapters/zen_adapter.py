"""OpenCode Zen 适配器 — 直连 Zen 的 OpenAI 兼容 API。

事实（2026-11-21 实测，见 docs/AGENT-PROBE.md）：
- Zen key 有效：GET /models 返回 200、69 个模型可见。
- 直连需带浏览器 UA，否则 Cloudflare 403 error 1010。
- 当前账户：付费模型 402 Insufficient balance；免费模型 429 Free usage limit reached。
  => 代码与认证没问题，是额度状态问题。充值 / 免费额度重置后即可用。

适配器用标准库 urllib（零依赖），key 从 opencode 的 auth.json 读取，
只在内存中使用：不回显、不写日志、不写盘。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from yoai.adapters.base import AdapterResult, PeerAdapter

DEFAULT_AUTH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
ZEN_CHAT_URL = "https://opencode.ai/zen/v1/chat/completions"
ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"
# Cloudflare 会拒绝无 UA 的 urllib 默认请求（403 / error 1010）
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


class ZenAdapter(PeerAdapter):
    """直连 OpenCode Zen 的 L2 适配器。"""

    level = "L2"

    def __init__(
        self,
        model: str = "gpt-5.4-nano",
        *,
        auth_path: str | Path = DEFAULT_AUTH,
        enabled: bool = True,
        timeout_s: float = 60.0,
        name: str = "OpenCode Zen",
        max_tokens: int = 512,
    ) -> None:
        super().__init__(name, enabled=enabled, timeout_s=timeout_s)
        self.model = model
        self.auth_path = Path(auth_path)
        self.max_tokens = max_tokens
        self.last_status = ""

    def _load_key(self) -> str:
        data = json.loads(self.auth_path.read_text(encoding="utf-8"))
        return str(data["opencode"]["key"])

    def available(self) -> bool:
        if not self.enabled or not self.auth_path.exists():
            return False
        try:
            return bool(self._load_key())
        except (OSError, ValueError, KeyError):
            return False

    def capabilities(self) -> list[str]:
        return ["chat", "auto_reply", "opencode_zen", f"model:{self.model}"]

    def send(self, message: str) -> AdapterResult:
        if not self.enabled:
            return AdapterResult(False, level=self.level, detail="适配器已禁用")
        try:
            key = self._load_key()
        except (OSError, ValueError, KeyError) as exc:
            return AdapterResult(False, level=self.level,
                                 detail=f"读取 Zen 认证失败：{type(exc).__name__}")

        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": self.max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            ZEN_CHAT_URL, data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": UA,
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout_s)
            data = json.loads(resp.read().decode("utf-8"))
            self.last_status = "ok"
            text = data["choices"][0]["message"]["content"]
            return AdapterResult(True, text=str(text), level=self.level)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            self.last_status = f"http_{exc.code}"
            detail = _friendly_error(exc.code, raw)
            return AdapterResult(False, level=self.level, detail=detail,
                                 meta={"http_status": exc.code})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
            self.last_status = type(exc).__name__
            return AdapterResult(False, level=self.level,
                                 detail=f"Zen 调用失败：{type(exc).__name__}: {str(exc)[:120]}")

    @staticmethod
    def list_models(auth_path: str | Path = DEFAULT_AUTH) -> list[str]:
        """查询账户可见的 Zen 模型 id（key 仅在内存）。"""
        key = json.loads(Path(auth_path).read_text(encoding="utf-8"))["opencode"]["key"]
        req = urllib.request.Request(
            ZEN_MODELS_URL,
            headers={"Authorization": f"Bearer {key}", "User-Agent": UA, "Accept": "application/json"},
        )
        data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))
        items = data.get("data", []) if isinstance(data, dict) else data
        return [str(m.get("id", "")) for m in items if isinstance(m, dict)]


def _friendly_error(code: int, raw: str) -> str:
    """把 API 错误翻成人话，不吞细节。"""
    try:
        msg = json.loads(raw).get("error", {}).get("message", raw[:120])
    except (ValueError, AttributeError):
        msg = raw[:120]
    if code == 402:
        return f"Zen 余额不足（402）：{msg}。请到 OpenCode 控制台充值后再试。"
    if code == 429:
        return f"Zen 额度已用尽（429）：{msg}。免费额度重置或充值后再试。"
    if code == 403:
        return f"Zen 访问被拒（403）：{msg}。"
    return f"Zen HTTP {code}：{msg}"
