"""真实模型网关的共享基础设施。

安全约定：所有 key 只在内存中使用，不回显、不写日志、不写盘、不进 AdapterResult。
.env 读取仅用于取 api key / base_url / model，跳过注释与空行。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def read_env_file(path: str | Path) -> dict[str, str]:
    """读取 KEY=VALUE 格式的 .env（跳过注释与空行，去引号）。"""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    """发一个 JSON POST，返回解析后的 dict；错误统一抛 model_error。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    all_headers = {"Content-Type": "application/json", "User-Agent": UA, **headers}
    req = urllib.request.Request(url, data=body, headers=all_headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout_s)
        return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise ModelHTTPError(exc.code, _extract_api_message(raw)) from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ModelTransportError(f"{type(exc).__name__}: {exc}") from None


class ModelHTTPError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ModelTransportError(Exception):
    pass


def _extract_api_message(raw: str) -> str:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in ("message", "error", "detail"):
                val = data.get(key)
                if isinstance(val, str):
                    return val[:200]
                if isinstance(val, dict) and isinstance(val.get("message"), str):
                    return val["message"][:200]
    except (ValueError, TypeError):
        pass
    return raw[:200]


def friendly_http_error(status: int, message: str) -> str:
    """把 HTTP 状态翻成人话，不吞细节。"""
    if status in (401, 403):
        return f"认证被拒（{status}）：{message}。检查 key/网关配置。"
    if status == 402:
        return f"余额不足（{status}）：{message}。"
    if status == 429:
        return f"请求过于频繁或额度用尽（{status}）：{message}。"
    if 500 <= status < 600:
        return f"网关服务错误（{status}）：{message}。"
    return f"HTTP {status}：{message}"
