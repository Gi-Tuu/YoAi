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


def test_model_timeout_default_no_hard_cap(monkeypatch, tmp_path):
    """总时长硬上限默认取消：长推理持续出流不应被误杀（截图里的 180s TimeoutError）。
    卡住交给传输层 socket 超时，重连交给 transport_retries；只有显式设正数才加回上限。
    """
    from yoai.agent import YoAiAgent

    monkeypatch.delenv("YOAI_MODEL_TIMEOUT", raising=False)
    a = YoAiAgent(data_dir=tmp_path / "a")
    assert a.core.model_timeout is None
    assert a.core._loop.model_timeout is None   # 真正生效在 loop

    monkeypatch.setenv("YOAI_MODEL_TIMEOUT", "0")
    assert YoAiAgent(data_dir=tmp_path / "b").core.model_timeout is None

    monkeypatch.setenv("YOAI_MODEL_TIMEOUT", "-5")
    assert YoAiAgent(data_dir=tmp_path / "b2").core.model_timeout is None

    monkeypatch.setenv("YOAI_MODEL_TIMEOUT", "240")
    assert YoAiAgent(data_dir=tmp_path / "c").core.model_timeout == 240.0

    monkeypatch.setenv("YOAI_MODEL_TIMEOUT", "not-a-number")
    assert YoAiAgent(data_dir=tmp_path / "d").core.model_timeout is None


def test_readonly_tools_are_discoverable(monkeypatch, tmp_path):
    """挂载只读根时，file_list/shell_run 描述必须引导模型改用 file_ro_*，
    否则模型会反复用沙箱工具试 E 盘路径并误判"能力缺失"（2026-11-25 实测）。"""
    from yoai.agent import YoAiAgent
    from yoai.bootstrap import agent_kwargs

    monkeypatch.setenv("YOAI_READONLY_ROOTS", str(tmp_path))
    kw = agent_kwargs(tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    a = YoAiAgent(**kw)
    specs = {s.name: s for s in a._all_tool_specs}
    assert "file_ro_list" in specs and "file_ro_read" in specs
    for name in ("file_list", "shell_run"):
        assert "file_ro_list" in specs[name].description, f"{name} 缺少只读工具引导"
    assert "宿主机" in specs["file_ro_list"].description


def test_readonly_tools_are_discoverable(monkeypatch, tmp_path):
    """挂载只读根时，file_list/shell_run 描述必须引导模型改用 file_ro_*，
    否则模型会反复用沙箱工具试 E 盘路径并误判"能力缺失"（2026-11-25 实测）。"""
    from yoai.agent import YoAiAgent
    from yoai.bootstrap import agent_kwargs

    monkeypatch.setenv("YOAI_READONLY_ROOTS", str(tmp_path))
    kw = agent_kwargs(tmp_path / "data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    a = YoAiAgent(**kw)
    specs = {s.name: s for s in a._all_tool_specs}
    assert "file_ro_list" in specs and "file_ro_read" in specs
    for name in ("file_list", "shell_run"):
        assert "file_ro_list" in specs[name].description, f"{name} 缺少只读工具引导"
    assert "宿主机" in specs["file_ro_list"].description
