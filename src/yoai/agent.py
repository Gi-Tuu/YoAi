"""YoAi Agent 门面 — 组装 Core + Personal Context + Goal Manager。

计划定位：YoAi Personal Agent 是终端产品，YAI Agent Core 是底层内核。
本模块是二者的接缝：它持有个人状态，把能力交给 Core 内省，并把 Core
的事件流原样透出——YoAi 不重造内核的任何执行/规划/治理逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from yai_core import AgentCore, EventType, ModelResponse, ScriptedModel, discover

from yoai.capabilities import PersonalCapabilities
from yoai.context import PersonalContext
from yoai.goals import GoalManager


def _default_data_dir() -> Path:
    """数据目录：开发期在项目根/output；打包后固定在 exe 同目录/output。

    打包（PyInstaller onefile）会把 __file__ 指到临时解压目录 _MEIxxxx，
    若沿用 __file__ 推导，每次启动都会换目录、个人状态全部丢失。
    """
    if getattr(sys, "frozen", False):
        # sys.executable = 用户双击的 exe 路径
        return Path(sys.executable).resolve().parent / "output"
    return Path(__file__).resolve().parents[2] / "output"


DEFAULT_DATA_DIR = _default_data_dir()


def _default_model() -> ScriptedModel:
    """未注入模型时的占位模型：明确告知未配置，不伪造答案。"""
    return ScriptedModel([ModelResponse(content="YoAi 已就绪，但尚未配置模型。")])


class YoAiAgent:
    """YoAi 产品门面：一个可被 CLI/未来 Web/桌面壳持有的长期个人智能体。"""

    def __init__(
        self,
        model: Any = None,
        data_dir: str | Path | None = None,
        memory: Any = None,
        outcome_verifier: Any = "auto",
        temporal_memory: bool | Any = True,
        tool_filter: Any = None,
    ) -> None:
        """tool_filter: 可选 callable(task)->set[str]|None，在每次 astream 开始时按任务
        过滤可用工具（专家白名单接线）。None 或返回 None 表示不限制。默认不启用，
        生产行为完全不变。就地修改 registry 对象以保持 loop 持有的引用一致。"""
        data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.context = PersonalContext(data_dir / "context.json")
        self.goals = GoalManager(data_dir / "goals.json")
        # 时间记忆层（YoAi 内覆盖层）：默认启用，传 False 可关闭以兼容旧行为。
        if temporal_memory is False:
            self.temporal_memory = None
        elif temporal_memory is True:
            from yoai.temporal_memory import TemporalMemory
            self.temporal_memory = TemporalMemory(data_dir / "temporal_memory.json")
        else:
            self.temporal_memory = temporal_memory   # 允许注入自定义实例
        self.capabilities = PersonalCapabilities(
            self.context, self.goals, self.temporal_memory
        )
        model = _default_model() if model is None else model
        self.model = model   # 宿主可读（如证据采集取真实 usage）
        # 验收器：auto=用 YoAi 真实 verifier（收据 + 查个人事实状态）；
        # None=关闭（Core 默认不验收）；也可注入自定义 verifier。
        from yoai.verification import build_default_verifier, make_context_assertion
        if outcome_verifier == "auto":
            verifier = build_default_verifier(make_context_assertion(self.context))
        else:
            verifier = outcome_verifier
        # memory 必须在构造时传入：Core 的 AgentLoop 在构造时就绑定 memory 引用，
        # 事后替换 core.memory 不会生效（loop 仍持旧实例）。
        core_kwargs: dict[str, Any] = {"outcome_verifier": verifier}
        if memory is not None:
            core_kwargs["memory"] = memory
        self.core = AgentCore(model, **core_kwargs)
        # Core 内省公开方法 → ToolSpec，注册进统一 ToolRegistry。
        self._all_tool_specs = discover(self.capabilities)
        self.core.register_tools(self._all_tool_specs)
        self.tool_filter = tool_filter
        self._active_whitelist: set[str] | None = None

    def _apply_tool_filter(self, task: str) -> None:
        """按 tool_filter 结果就地重建工具表；保持 core 与 loop 共享的 registry 引用不变。

        就地改 _tools 而不是替换 registry 对象——loop 在构造时已绑定旧引用（见 agent.py
        memory 同理）。这是 YoAi 内对 Core 对象的操作，不修改 Core 源码。
        """
        if self.tool_filter is None:
            return
        whitelist = self.tool_filter(task)
        if whitelist == self._active_whitelist:
            return   # 无变化，避免每次重建
        reg = self.core.registry
        if whitelist is None:
            target = self._all_tool_specs
        else:
            allowed = set(whitelist)
            target = [s for s in self._all_tool_specs if s.name in allowed]
        # 就地替换：先清后注册（ToolRegistry 无公开 clear，_tools 是其内部 dict）
        reg._tools.clear()
        reg.register_many(target)
        self._active_whitelist = set(whitelist) if whitelist is not None else None

    def list_tools(self) -> list[str]:
        """列出当前已注册的工具名。"""
        return [t["name"] for t in self.core.list_tools()]

    async def astream(self, task: str):
        """驱动 Core 执行任务，逐条透出内核事件（不改动事件语义）。"""
        self._apply_tool_filter(task)
        async for event in self.core.astream(task):
            yield event

    @staticmethod
    def is_done(event: Any) -> bool:
        """事件是否为任务完成。"""
        return event.type == EventType.DONE
