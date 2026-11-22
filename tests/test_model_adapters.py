"""真实模型适配器测试：解析、错误路径、key 不回显、usage。

用假响应 + monkeypatch post_json，不真联网、不碰真实 key。
真实调用已在 docs/AGENT-PROBE.md 记录（HTTP 200 + 真实回答）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from yoai.models.deepseek_adapter import DeepSeekAnthropicAdapter, _extract_text as ds_extract  # noqa: E402
from yoai.models.http_base import ModelHTTPError, ModelTransportError, read_env_file  # noqa: E402
from yoai.models.suanli_adapter import SuanliAdapter, _extract_text as sl_extract  # noqa: E402


# --- 解析 ---
def test_anthropic_extract_skips_thinking():
    data = {
        "content": [
            {"type": "thinking", "thinking": "内部思考"},
            {"type": "text", "text": "收到"},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    text, usage = ds_extract(data)
    assert text == "收到" and "内部思考" not in text
    assert usage["total_tokens"] == 15


def test_openai_extract():
    data = {
        "choices": [{"message": {"content": "你好"}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
    }
    text, usage = sl_extract(data)
    assert text == "你好" and usage["total_tokens"] == 10


def test_suanli_extract_falls_back_to_reasoning_when_content_empty():
    """deepseek 思考模型 content=None 时，答案在 reasoning_content，不能丢。

    真实事故：第一轮 LongMemEval 11 题空文本，根因就在这里。
    """
    data = {
        "choices": [{"message": {
            "content": None,
            "reasoning_content": "The user said the limit was increased to two cups.",
        }}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    text, usage = sl_extract(data)
    assert "two cups" in text and usage["total_tokens"] == 15


def test_suanli_extract_prefers_content_over_reasoning():
    """有正式 content 时优先用它，不把思考过程当答案。"""
    data = {
        "choices": [{"message": {
            "content": "正式答案",
            "reasoning_content": "内部思考过程",
        }}],
        "usage": {},
    }
    text, _ = sl_extract(data)
    assert text == "正式答案" and "内部思考" not in text


def test_read_env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nA=1\nB=\"quoted\"\nC='single'\nD\n", encoding="utf-8")
    d = read_env_file(p)
    assert d == {"A": "1", "B": "quoted", "C": "single"}


# --- 成功路径（假响应） ---
def test_deepseek_success_with_fake_response(monkeypatch):
    import yoai.models.deepseek_adapter as mod
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://fake")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk_fake_secret")
    monkeypatch.setenv("ANTHROPIC_MODEL", "fake-model")

    def fake_post(url, payload, headers, timeout):
        assert headers["x-api-key"] == "sk_fake_secret"
        return {"content": [{"type": "text", "text": "真回答"}],
                "usage": {"input_tokens": 3, "output_tokens": 2}}

    monkeypatch.setattr(mod, "post_json", fake_post)
    a = DeepSeekAnthropicAdapter()
    assert a.available() is True
    r = a.send("hi")
    assert r.ok is True and r.text == "真回答"
    assert "sk_fake_secret" not in r.detail and "sk_fake_secret" not in str(r.meta)


def test_suanli_success_with_fake_response(monkeypatch, tmp_path):
    import yoai.models.suanli_adapter as mod
    p = tmp_path / ".env"
    p.write_text("OPENAI_BASE_URL=https://fake/v1\nOPENAI_API_KEY=sk_secret_xyz\n"
                 "LLM_MODEL=fake-model\n", encoding="utf-8")

    def fake_post(url, payload, headers, timeout):
        assert headers["Authorization"] == "Bearer sk_secret_xyz"
        return {"choices": [{"message": {"content": "算里回答"}}],
                "usage": {"total_tokens": 9}}

    monkeypatch.setattr(mod, "post_json", fake_post)
    a = SuanliAdapter(env_path=p)
    r = a.send("hi")
    assert r.ok is True and r.text == "算里回答"
    assert "sk_secret_xyz" not in r.detail and "sk_secret_xyz" not in str(r.meta)


# --- 错误路径 ---
def test_http_error_friendly(monkeypatch):
    import yoai.models.deepseek_adapter as mod
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://fake")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "k")
    monkeypatch.setenv("ANTHROPIC_MODEL", "m")

    def bad(url, payload, headers, timeout):
        raise ModelHTTPError(429, "rate limited")

    monkeypatch.setattr(mod, "post_json", bad)
    r = DeepSeekAnthropicAdapter().send("hi")
    assert r.ok is False and "429" in r.detail and "额度" in r.detail


def test_transport_error(monkeypatch):
    import yoai.models.suanli_adapter as mod
    def bad(url, payload, headers, timeout):
        raise ModelTransportError("connection refused")

    monkeypatch.setattr(mod, "post_json", bad)
    r = SuanliAdapter(env_path=Path("/nonexistent")).send("hi")
    assert r.ok is False  # 先因配置缺失返回，不打网络
    # 造一个能通过的假 .env 再测 transport
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".env"
        p.write_text("OPENAI_BASE_URL=https://fake\nOPENAI_API_KEY=k\nLLM_MODEL=m\n", encoding="utf-8")
        r2 = SuanliAdapter(env_path=p).send("hi")
        assert r2.ok is False and "连接失败" in r2.detail


def test_missing_config_is_unavailable(tmp_path):
    a = SuanliAdapter(env_path=tmp_path / "missing.env")
    assert a.available() is False
    r = a.send("hi")
    assert r.ok is False and "缺少" in r.detail
