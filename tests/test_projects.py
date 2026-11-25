"""项目模式端到端守护：项目 CRUD / 写工具挂载 / 路径越界 / 记忆隔离 / 权限联动。

定位 2026-11-25 所有者需求：聊天模式留沙箱；项目模式绑定宿主机文件夹可写，
full 免审批、smart/manual 走审批；项目记忆互相隔离。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from yoai.agent import YoAiAgent
from yoai.bootstrap import PERMISSION_LEVELS, apply_permission_level
from yoai.project import ProjectError, ProjectStore, resolve_in_project
from yoai.project_tools import PROJECT_WRITE_TOOLS, project_tool_specs
from yoai.session import Session, SessionManager


def test_project_store_crud_and_path_validation(tmp_path):
    s = ProjectStore(tmp_path / "projects")
    folder = tmp_path / "myproj"
    folder.mkdir()
    (folder / "src").mkdir()

    proj = s.create("我的项目", str(folder))
    assert proj.name == "我的项目" and s.get(proj.id) is proj
    assert len(s.list_projects()) == 1

    # 重复创建同一文件夹被拒
    with pytest.raises(ProjectError):
        s.create("重复", str(folder))

    # 不存在路径 / 非文件夹被拒
    with pytest.raises(ProjectError):
        s.create("坏路径", str(tmp_path / "nope"))

    assert s.delete(proj.id) is True
    assert s.get(proj.id) is None


def test_project_tools_confined_and_writable(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    specs = project_tool_specs(folder, "proj")
    names = [sp.name for sp in specs]
    assert set(names) == {"proj_list", "proj_read", "proj_write", "proj_patch"}
    assert PROJECT_WRITE_TOOLS == {"proj_write", "proj_patch"}

    # 路径越界拦截（含 ..）
    with pytest.raises(ProjectError):
        resolve_in_project(folder, "../../etc/passwd")

    # 直接调 handler 验证写→读→patch 闭环（tools spec 的 handler）
    handlers = {sp.name: sp.handler for sp in specs}
    created = json.loads(handlers["proj_write"]("hello.txt", "v1"))
    assert created["created"] is True
    read = json.loads(handlers["proj_read"]("hello.txt"))
    assert read["content"] == "v1" and read["sha256"]
    patched = json.loads(handlers["proj_patch"]("hello.txt", "v2", read["sha256"]))
    assert patched["updated"] is True
    # 过期 sha256 被拒（乐观并发）
    conflict = handlers["proj_patch"]("hello.txt", "v3", read["sha256"])
    assert "冲突" in conflict
    assert (folder / "hello.txt").read_text(encoding="utf-8") == "v2"


def test_project_agent_mounts_write_tools_and_isolates_memory(tmp_path):
    folder_a = tmp_path / "projA"
    folder_b = tmp_path / "projB"
    folder_a.mkdir(); folder_b.mkdir()
    kwargs_base = {"builtin_tools": True}
    calls: list[dict] = []

    def kwargs_for(sess):
        if sess.mode != "project":
            return None
        return {"project_root": str(folder_a if sess.project_id == "a" else folder_b),
                "project_name": sess.project_id}

    def mem_dir_for(sess):
        return tmp_path / "mem" / sess.project_id if sess.mode == "project" else None

    sm = SessionManager(
        tmp_path / "sessions", model_factory=lambda: None,
        agent_kwargs=kwargs_base,
        agent_kwargs_for_session=kwargs_for,
        memory_dir_for_session=mem_dir_for,
    )
    chat = sm.create("聊天")
    pa = sm.create("A", mode="project", project_id="a")
    sm.create("B", mode="project", project_id="b")

    a = sm.agent_for(pa.id)
    assert {"proj_write", "proj_patch"}.issubset(set(a.list_tools()))

    chat_agent = sm.agent_for(chat.id)
    assert not any(t.startswith("proj_") for t in chat_agent.list_tools()), "聊天模式不应有项目工具"

    # 记忆目录隔离：项目 A/B 各自独立，聊天模式用全局共享目录
    pb = next(s for s in sm.list_sessions() if s.project_id == "b")
    a_agent = sm.agent_for(pa.id)
    b_agent = sm.agent_for(pb.id)
    a_mem = a_agent.context.path.parent
    b_mem = b_agent.context.path.parent
    chat_mem = chat_agent.context.path.parent
    assert a_mem != b_mem, "两个项目的记忆目录必须隔离"
    assert chat_mem not in (a_mem, b_mem), "聊天模式应全局共享"


def test_write_tools_respect_permission_levels(tmp_path):
    """full(allow_all) 直接放行；smart/manual(auto) 下 proj_write 不在白名单 → ASK。"""
    from yai_core.policy import AllowlistPolicy
    from yai_core.spi.policy import PermissionDecision as PD

    p = AllowlistPolicy(allowed={"proj_list", "proj_read", "proj_write"}, mode="auto")
    apply_permission_level(p, "full")
    assert asyncio.run(p.check("proj_write", {})) == PD.ALLOW

    apply_permission_level(p, "smart")
    assert asyncio.run(p.check("proj_list", {})) == PD.ALLOW   # 读自动
    assert asyncio.run(p.check("proj_write", {})) == PD.ASK    # 写审批

    apply_permission_level(p, "manual")
    assert asyncio.run(p.check("proj_write", {})) == PD.ASK
