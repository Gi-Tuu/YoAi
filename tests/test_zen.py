"""Zen 适配器测试：成功路径、402/429 错误翻译、key 不回显、模型列表。

用假 auth.json + monkeypatch urllib，不真联网、不碰真实 key。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from yoai.adapters.zen_adapter import ZenAdapter  # noqa: E402


def _fake_auth(tmp_path: Path) -> Path:
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"opencode": {"type": "api", "key": "oc_test_fake_key"}}),
                 encoding="utf-8")
    return p


def _fake_response(payload: dict):
    class R:
        status = 200

        def read(self):
            return json.dumps(payload).encode("utf-8")
    return R()


def test_zen_available_with_key(tmp_path):
    a = ZenAdapter(auth_path=_fake_auth(tmp_path))
    assert a.available() is True
    assert a.capabilities()[0] == "chat"
    assert "model:gpt-5.4-nano" in a.capabilities()


def test_zen_unavailable_without_auth(tmp_path):
    a = ZenAdapter(auth_path=tmp_path / "missing.json")
    assert a.available() is False
    r = a.send("hi")
    assert r.ok is False and "认证" in r.detail


def test_zen_success(monkeypatch, tmp_path):
    import yoai.adapters.zen_adapter as mod

    monkeypatch.setattr(
        mod.urllib.request, "urlopen",
        lambda req, timeout: _fake_response({"choices": [{"message": {"content": "收到"}}]}),
    )
    a = ZenAdapter(auth_path=_fake_auth(tmp_path))
    r = a.send("只回复收到")
    assert r.ok is True and r.text == "收到" and r.level == "L2"


def test_zen_402_friendly(monkeypatch, tmp_path):
    import urllib.error
    import yoai.adapters.zen_adapter as mod

    def raise402(req, timeout):
        body = json.dumps({"error": {"message": "Insufficient balance"}}).encode()
        raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {}, io.BytesIO(body))

    monkeypatch.setattr(mod.urllib.request, "urlopen", raise402)
    a = ZenAdapter(auth_path=_fake_auth(tmp_path))
    r = a.send("hi")
    assert r.ok is False and "余额不足" in r.detail
    assert r.meta.get("http_status") == 402


def test_zen_429_friendly(monkeypatch, tmp_path):
    import urllib.error
    import yoai.adapters.zen_adapter as mod

    def raise429(req, timeout):
        body = json.dumps({"error": {"message": "Free usage limit reached"}}).encode()
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))

    monkeypatch.setattr(mod.urllib.request, "urlopen", raise429)
    a = ZenAdapter(auth_path=_fake_auth(tmp_path))
    r = a.send("hi")
    assert r.ok is False and "额度已用尽" in r.detail


def test_zen_key_never_in_detail(monkeypatch, tmp_path):
    """关键安全测试：任何返回文本都不得包含 key。"""
    import urllib.error
    import yoai.adapters.zen_adapter as mod

    def raise403(req, timeout):
        body = json.dumps({"error": {"message": "bad"}}).encode()
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(body))

    monkeypatch.setattr(mod.urllib.request, "urlopen", raise403)
    a = ZenAdapter(auth_path=_fake_auth(tmp_path))
    r = a.send("hi")
    assert "oc_test_fake_key" not in r.detail
    assert "oc_test_fake_key" not in json.dumps(a.describe())
