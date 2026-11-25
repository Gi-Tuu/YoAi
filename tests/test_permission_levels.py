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


def test_user_config_per_session_isolation(tmp_path):
    """档位按会话独立：改 A 不影响 B，新会话用全局默认。"""
    cfg = UserConfig(tmp_path)
    assert cfg.permission_level("s1") == ""      # 未设置 → 让环境/默认生效
    assert cfg.default_level() == ""

    # s1 设 manual，s2 不受影响
    assert cfg.set_permission("s1", "manual")
    assert cfg.permission_level("s1") == "manual"
    assert cfg.permission_level("s2") == ""

    # s2 首次使用：用全局默认并固化
    cfg.apply_default_to("s2", "full")
    assert cfg.permission_level("s2") == "full"
    assert cfg.permission_level("s1") == "manual"

    # 改 s2 不影响 s1
    cfg.set_permission("s2", "smart")
    assert cfg.permission_level("s2") == "smart"
    assert cfg.permission_level("s1") == "manual"

    # 新会话默认来自 permission_default，不是某个会话的档位
    cfg.set_permission("", "manual")   # 全局默认
    assert cfg.default_level() == "manual"
    assert UserConfig(tmp_path).permission_level("s3") == "manual"

    # agent_kwargs 构造时读全局默认（新会话初始值）
    assert agent_kwargs(tmp_path)["policy"].mode == "auto"
    assert agent_kwargs(tmp_path)["policy"].allowed == set()   # manual=空名单

    # 损坏的 config 不致命
    (tmp_path / "config.json").write_text("not json", encoding="utf-8")
    assert UserConfig(tmp_path).permission_level("s1") == ""


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


def test_policy_copy_prevents_shared_template_pollution():
    """回归：SessionManager 的 policy 模板被所有会话共享，改一个不能污染其他。"""
    import copy
    template = AllowlistPolicy(allowed={"remember_fact"}, mode="auto")
    shared_kwargs = {"policy": template}   # 模拟 SessionManager._agent_kwargs

    # 会话 A 改档：必须先复制，不能动模板
    a = copy.copy(shared_kwargs["policy"])
    apply_permission_level(a, "full")
    assert template.mode == "auto" and "remember_fact" in template.allowed

    # 会话 B 从模板构造：仍是 smart，没被 A 污染
    b = copy.copy(shared_kwargs["policy"])
    assert permission_level_of(b) == "smart"


def test_policy_copy_prevents_shared_template_pollution():
    """回归：SessionManager 的 policy 模板被所有会话共享，改一个不能污染其他。"""
    import copy
    template = AllowlistPolicy(allowed={"remember_fact"}, mode="auto")
    shared_kwargs = {"policy": template}   # 模拟 SessionManager._agent_kwargs

    # 会话 A 改档：必须先复制，不能动模板
    a = copy.copy(shared_kwargs["policy"])
    apply_permission_level(a, "full")
    assert template.mode == "auto" and "remember_fact" in template.allowed

    # 会话 B 从模板构造：仍是 smart，没被 A 污染
    b = copy.copy(shared_kwargs["policy"])
    assert permission_level_of(b) == "smart"
