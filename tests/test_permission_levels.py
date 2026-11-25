"""权限三档守护测试：UI 档位 → Core policy → 持久化 → 跨会话生效。"""

from __future__ import annotations

from pathlib import Path

from yai_core.policy import AllowlistPolicy

from yoai.bootstrap import (PERMISSION_LEVELS, agent_kwargs,
                            apply_permission_level, permission_level_of)
from yoai.user_config import UserConfig


def test_three_levels_map_to_core_policy():
    policy = AllowlistPolicy(allowed={"remember_fact", "file_create"}, mode="auto")

    apply_permission_level(policy, "full")
    assert policy.mode == "allow_all" and policy.allowed == set()
    assert permission_level_of(policy) == "full"

    apply_permission_level(policy, "smart")
    assert policy.mode == "auto" and "remember_fact" in policy.allowed
    assert "file_create" not in policy.allowed   # 写操作不在白名单
    assert permission_level_of(policy) == "smart"

    apply_permission_level(policy, "manual")
    assert policy.mode == "auto" and policy.allowed == set()
    assert permission_level_of(policy) == "manual"

    assert apply_permission_level(policy, "bogus") != ""
    assert set(PERMISSION_LEVELS) == {"full", "smart", "manual"}


def test_permission_decisions_match_levels():
    """三档的实际决策：full 全放行 / smart 写类询问 / manual 全询问。"""
    import asyncio
    policy = AllowlistPolicy()

    async def decide(level: str, tool: str):
        apply_permission_level(policy, level)
        return await policy.check(tool, {})

    from yai_core.spi.policy import PermissionDecision as PD
    assert asyncio.run(decide("full", "file_create")) == PD.ALLOW
    assert asyncio.run(decide("smart", "file_read")) == PD.ALLOW
    assert asyncio.run(decide("smart", "file_create")) == PD.ASK
    assert asyncio.run(decide("manual", "file_read")) == PD.ASK
    assert asyncio.run(decide("manual", "remember_fact")) == PD.ASK


def test_user_config_persist_and_agent_kwargs(tmp_path):
    """档位落 config.json 后，重建 agent 的构造参数也生效（跨会话关键）。"""
    cfg = UserConfig(tmp_path)
    assert cfg.permission_level() == ""      # 未设置 → 让环境/默认生效

    cfg.save({"permission_level": "manual"})
    assert UserConfig(tmp_path).permission_level() == "manual"

    kwargs = agent_kwargs(tmp_path)
    policy = kwargs["policy"]
    assert policy.mode == "auto" and policy.allowed == set()

    cfg.save({"permission_level": "full"})
    assert agent_kwargs(tmp_path)["policy"].mode == "allow_all"

    # 损坏的 config 不致命
    (tmp_path / "config.json").write_text("not json", encoding="utf-8")
    assert UserConfig(tmp_path).permission_level() == ""


def test_permission_state_protocol_contract():
    """协议字段与前端 types/ipc.ts 契约一致。"""
    import sys
    tauri = Path(__file__).resolve().parents[1] / "apps" / "desktop-tauri" / "runtime"
    sys.path.insert(0, str(tauri))
    from protocol import permission_state
    msg = permission_state(level="manual", description="每个工具都弹窗")
    assert msg["type"] == "permission.state"
    assert {"level", "description"} <= set(msg)
    assert msg["level"] in PERMISSION_LEVELS
