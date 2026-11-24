"""权限档位开关测试：默认 auto，YOAI_PERMISSION_MODE=allow_all 全放行。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.policy import AllowlistPolicy

from yoai.desktop.app import _agent_kwargs


def test_default_is_auto(monkeypatch):
    monkeypatch.delenv("YOAI_PERMISSION_MODE", raising=False)
    kwargs = _agent_kwargs()
    policy = kwargs["policy"]
    assert isinstance(policy, AllowlistPolicy)
    assert policy.mode == "auto"
    assert "file_create" not in policy.allowed   # 文件写必须走确认
    assert "file_read" in policy.allowed


def test_allow_all_env(monkeypatch):
    monkeypatch.setenv("YOAI_PERMISSION_MODE", "allow_all")
    policy = _agent_kwargs()["policy"]
    assert policy.mode == "allow_all"


def test_allow_all_env_case_insensitive(monkeypatch):
    monkeypatch.setenv("YOAI_PERMISSION_MODE", "  ALLOW_ALL  ")
    policy = _agent_kwargs()["policy"]
    assert policy.mode == "allow_all"


def test_unknown_env_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("YOAI_PERMISSION_MODE", "garbage")
    policy = _agent_kwargs()["policy"]
    assert policy.mode == "auto"


def test_selfcheck_forces_allow_all(monkeypatch):
    monkeypatch.delenv("YOAI_PERMISSION_MODE", raising=False)
    policy = _agent_kwargs(auto_approve=True)["policy"]
    assert policy.mode == "allow_all"
