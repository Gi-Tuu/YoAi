"""YoAi Agent 门面 — 组装 Core + Personal Context + Goal Manager。

计划定位：YoAi Personal Agent 是终端产品，YAI Agent Core 是底层内核。
本模块是二者的接缝：它持有个人状态，把能力交给 Core 内省，并把 Core
的事件流原样透出——YoAi 不重造内核的任何执行/规划/治理逻辑。
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yai_core import AgentCore, EventType, ModelResponse, ScriptedModel, discover


@dataclass
class _YoAiType:
    """YoAi 自定义事件类型（worker 只读 .value，不改 Core 的 EventType enum）。"""
    value: str


@dataclass
class YoAiEvent:
    """YoAi 侧补充事件（thinking 等 Core 不发但 UI 要展示的过程信息）。"""
    type: Any
    data: dict[str, Any]

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
        memory_fallback: bool = False,
        number_supplement: bool = False,
        memory_intent_routing: bool = True,
        builtin_tools: bool = False,
        workspace_root: str | Path | None = None,
        readonly_roots: list[str | Path] | None = None,
        project_root: str | Path | None = None,
        project_name: str = "",
        file_change_store: Any = None,   # FileChangeStore：记录项目写操作
        change_context: dict[str, str] | None = None,  # {session_id, project_id}
        channel: Any = None,
        policy: Any = None,
        mcp_manager: Any = None,
        skill_store: Any = None,
        model_timeout: float | None = "env",  # type: ignore[assignment]
    ) -> None:
        """tool_filter: 可选 callable(task)->set[str]|None，在每次 astream 开始时按任务
        过滤可用工具（专家白名单接线）。None 或返回 None 表示不限制。默认不启用，
        生产行为完全不变。就地修改 registry 对象以保持 loop 持有的引用一致。
        memory_fallback: 阶段B——模型本轮一个记忆都没写时，是否用确定性规则兜底。
        默认 False（保守，不改既有行为）；验证后再决定是否设默认。
        number_supplement: 阶段C——无条件叠加"数字+名词"事实抽取。默认 False：
        全量A/B已证不显著（63.0%→63.2%, p=1.0），仅数字密集场景按需开启。
        memory_intent_routing: 默认 True——YoAi 工具优先路由：只要有工具就走 REACT
        注入完整 schema，让模型自己决定调不调。根治 DIRECT"不给 schema 却给工具目录"
        导致模型吐 DSML 被拒的静默失败（2026-11-24）。不再靠关键词表打地鼠。
        继承 Core 公开 Router 类，不改内核、升级兼容；传 False 恢复纯 Core 行为。
        builtin_tools: 默认 False——是否注册实操工具（file_list/read/create/patch、
        web_search/web_fetch）。开启后 AI 能读写 项目内 workspace/ 目录 内的文件、
        访问公开网页；写操作限白名单子目录并带 Core 的 filesystem_gate。
        保守默认关闭，验证通过后再决定是否设默认。
        workspace_root: builtin_tools 的文件根目录，缺省 项目内 workspace/ 目录。"""
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
        self.memory_fallback = bool(memory_fallback)
        self.number_supplement = bool(number_supplement)
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
        # discovery：Core 只有配了发现源才把 request_capability 注册为 meta_tool
        # （由 loop 拦截）；YoAi 不再手动注册，根治"应由 Agent Loop 直接处理"报错。
        from yai_core.discovery import StaticCatalog
        # 单次模型调用总时长上限：默认**不设**（None）。
        # 历史：Core 默认 60s 会误杀 spark-x2.6（带 26+ 工具 schema 首 token 实测
        # 40s+），曾升到 180s；但长推理/大文件任务仍会被"总时长"硬截断，
        # 而这类调用本身一直在正常出 token——硬上限解决不了卡住，只会误杀慢活。
        # 现在交给传输层：socket 读超时负责"卡住"（连续 60s 无增量即失败），
        # SuanliAdapter 的 transport_retries 负责"重连"；两者都不是总时长上限。
        # 如需强制上限，显式设 YOAI_MODEL_TIMEOUT=<秒数>；0/负数/非法值均视为不设。
        # 内核零改动——Core 公开构造参数，升级兼容。
        if model_timeout == "env":
            raw = os.environ.get("YOAI_MODEL_TIMEOUT", "0").strip()
            try:
                value = float(raw)
                resolved: float | None = value if value > 0 else None
            except ValueError:
                resolved = None      # 环境变量填错不致命，按默认不设上限处理
        else:
            resolved = model_timeout
        # 工具 schema 聚焦预算：Core 默认 24，超出后会让模型先做一次"只输出工具名
        # JSON 数组"的聚焦调用。推理模型（spark-x2.6）会把这个子任务误当成主任务，
        # 之后在正文里输出工具名数组而不是真正发 tool_calls（2026-11-25 实测：
        # 项目模式 30 工具触发聚焦 → 写文件全失败 + [object Object] 乱码）。
        # 调大预算让全部 schema 一次注入，跳过聚焦；内核零改动、公开构造参数。
        try:
            focus_budget = int(os.environ.get("YOAI_SCHEMA_BUDGET", "64").strip())
        except ValueError:
            focus_budget = 64
        core_kwargs: dict[str, Any] = {
            "outcome_verifier": verifier,
            "discovery": StaticCatalog([]),   # 空目录：允许声明缺口，不动态加工具
            "model_timeout": resolved,
            "full_schema_budget": focus_budget,
        }
        # 实操工具（文件/联网）：Core 公开 API 注册，内核零改动、升级兼容。
        if memory is not None:
            core_kwargs["memory"] = memory
        # 审批通道与权限策略在构造时绑定（Core 的 loop 持有引用，事后换无效）。
        if channel is not None:
            core_kwargs["channel"] = channel
        if policy is not None:
            core_kwargs["policy"] = policy
        # YoAi 侧路由：有工具就注入完整 schema（REACT），让模型自己决定调不调。
        # 根治 DIRECT"不给 schema 却给工具目录"的矛盾——不再靠词表打地鼠。
        # 继承 Core 公开类，不改内核、升级兼容；False 关闭恢复纯 Core 行为。
        if memory_intent_routing:
            from yoai.routing import YoAiRouter
            core_kwargs["router"] = YoAiRouter()
        self.core = AgentCore(model, **core_kwargs)
        # Core 内省公开方法 → ToolSpec，注册进统一 ToolRegistry。
        self.file_change_store = file_change_store
        self.change_context = dict(change_context or {})
        if mcp_manager is None:
            from yoai.mcp import McpManager
            mcp_manager = McpManager(data_dir)
        self.mcp_manager = mcp_manager
        if skill_store is None:
            from yoai.skills import SkillStore
            skill_store = SkillStore(data_dir)
        self.skill_store = skill_store
        self._all_tool_specs = self._build_all_specs(
            builtin_tools, workspace_root, readonly_roots, project_root, project_name)
        self.core.register_tools(self._all_tool_specs)
        # 插件热加载（2026-11-24）：data_dir/plugins/*.py 每轮 astream 前扫描，
        # 新增/变更的插件工具 diff 注册——旧会话不重启也能用上新工具。
        # 无 plugins 目录时零开销（不扫描）。
        self._plugin_dir: Path | None = (
            Path(data_dir) / "plugins" if data_dir is not None else None
        )
        self._plugin_mtimes: dict[str, float | None] = {}   # stem → 上次加载的 mtime
        self._plugin_tool_names: dict[str, str] = {}        # 工具名 → 来源插件 stem
        self.tool_filter = tool_filter
        self._active_whitelist: set[str] | None = None

    def _build_all_specs(
        self,
        builtin_tools: bool = False,
        workspace_root: str | Path | None = None,
        readonly_roots: list[str | Path] | None = None,
        project_root: str | Path | None = None,
        project_name: str = "",
    ) -> list[Any]:
        """构造基础工具表（capabilities + 实操 + meta），__init__ 与 refresh 共用。"""
        specs = discover(self.capabilities)
        # 实操工具（文件/联网）：Core 公开 API 注册，内核零改动、升级兼容。
        # 默认关闭，验证后再决定是否设默认。
        if builtin_tools:
            from yoai.tools_builtin import builtin_tool_specs, readonly_tool_specs
            specs = specs + builtin_tool_specs(workspace_root)
            # 只读挂载扩展目录（如宿主项目源码，供 AI 调试宿主自己）：
            # 仅 file_ro_list / file_ro_read，路径必须落在白名单根内，无写类操作。
            if readonly_roots:
                specs = specs + readonly_tool_specs(readonly_roots)
                # 可发现性：模型看到 file_list 就想读宿主机盘符，但那受沙箱限制必失败。
                # 在 Core 工具描述上追加提示（YoAi 侧包装，内核零改动）——
                # 引导它遇到绝对路径/盘符时立刻改用 file_ro_*。
                _hint = (
                    " 【YoAi 提示】本工具受工作区沙箱限制，不能访问宿主机盘符绝对路径"
                    "（如 <盘符>:\\...）。用户要看宿主机项目目录/文件时，改用 file_ro_list / file_ro_read"
                    "（path 传相对挂载根的路径，或留空列顶层）。"
                )
                for s in specs:
                    if s.name in ("file_list", "file_read", "shell_run"):
                        s.description = (s.description or "") + _hint
        # 项目模式：挂载项目文件夹的读写工具（严格限制在项目根内）。
        # 权限：proj_list/proj_read 进 smart 自动白名单；proj_write/patch 不在白名单
        # → smart/manual 档下走 Core 审批通道；full(allow_all) 档直接放行。
        if project_root is not None:
            from yoai.project_tools import project_tool_specs

            def _on_change(action: str, path: str, before: str, after: str) -> None:
                """项目写操作落记录（产物/改动 UI 的数据源）。失败不影响主流程。"""
                store = getattr(self, "file_change_store", None)
                if store is None:
                    return
                try:
                    store.append(
                        session_id=self.change_context.get("session_id", ""),
                        project_id=self.change_context.get("project_id", ""),
                        run_id=self.change_context.get("run_id", ""),
                        path=path, action=action, before=before, after=after,
                    )
                except Exception as exc:  # noqa: BLE001
                    import sys as _sys
                    print(f"[yoai] file change record failed: {exc}", file=_sys.stderr, flush=True)

            specs = specs + project_tool_specs(project_root, project_name, on_change=_on_change)
        # MCP：标准协议外部 server 暴露的工具，经 Core ToolSpec(source=mcp) 同构注册。
        # 配置无 server 时零开销；坏 server 不影响其它工具。
        manager = getattr(self, "mcp_manager", None)
        if manager is not None:
            try:
                specs = specs + manager.tool_specs()
            except Exception as exc:  # noqa: BLE001
                import sys as _sys
                print(f"[yoai] mcp discovery failed: {exc}", file=_sys.stderr, flush=True)
        # Skills：配置化技能包，提供 skill_list / skill_load 元工具。
        skill_store = getattr(self, "skill_store", None)
        if skill_store is not None:
            try:
                specs = specs + skill_store.tool_specs()
            except Exception as exc:  # noqa: BLE001
                import sys as _sys
                print(f"[yoai] skill discovery failed: {exc}", file=_sys.stderr, flush=True)
        # list_tools：模型自省能力边界（列全部工具名+描述），不再靠猜；
        # request_capability 由 Core 的 discovery 机制注册为 meta_tool 并拦截处理。
        specs.append(self._build_list_tools_spec())
        return specs

    def _build_list_tools_spec(self) -> Any:
        """构造 list_tools 工具：运行时读 Core registry（真实全量工具表）。"""
        import json

        from yai_core import build_spec

        def list_tools() -> str:
            """列出当前会话可用的全部工具（名称+一句话描述）。
            不确定自己能做什么、或找不到想要的工具时先调用它，不要靠猜。"""
            specs = self.core.registry.all() if self.core is not None else self._all_tool_specs
            return json.dumps(
                [{"name": s.name, "description": (s.description or "").strip()}
                 for s in specs],
                ensure_ascii=False, indent=1,
            )

        return build_spec(list_tools)

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

    # --- 工具热加载（2026-11-24）：旧会话不重启也能用上新工具 ---

    def _scan_plugins(self) -> list[Any]:
        """扫描插件目录，加载新增/变更的插件工具（mtime 去重）。

        插件约定：data_dir/plugins/*.py，导出 ``TOOLS``（ToolSpec 列表）
        或 ``build_tools() -> list[ToolSpec]``。坏插件跳过不反噬主任务，
        并记住失败时的 mtime（文件没再改就不反复重试）。
        """
        import importlib.util

        if self._plugin_dir is None or not self._plugin_dir.is_dir():
            return []
        specs: list[Any] = []
        for path in sorted(self._plugin_dir.glob("*.py")):
            stem = path.stem
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if self._plugin_mtimes.get(stem) == mtime:
                continue   # 未变化，跳过
            try:
                mod_name = f"yoai_plugin_{stem}_{int(mtime)}"
                spec_md = importlib.util.spec_from_file_location(mod_name, path)
                assert spec_md is not None and spec_md.loader is not None
                mod = importlib.util.module_from_spec(spec_md)
                spec_md.loader.exec_module(mod)
                tools = getattr(mod, "TOOLS", None)
                if tools is None and hasattr(mod, "build_tools"):
                    tools = mod.build_tools()
                if not isinstance(tools, list):
                    raise TypeError("插件需导出 TOOLS 列表或 build_tools() 返回列表")
                specs.extend(tools)
                self._plugin_mtimes[stem] = mtime   # 成功才记录；失败记 None 防重试
            except Exception:  # noqa: BLE001
                self._plugin_mtimes[stem] = None
        return specs

    def refresh_tools(self) -> list[str]:
        """重建工具表并注册新增项（diff 只补缺），返回本次新注册的工具名。

        - 插件目录有新/变更文件 → 加载并注册（同名插件工具可热替换）；
        - 插件工具与内置工具重名 → 跳过（不许插件覆盖内核/实操工具）；
        - registry 缺了 _all_tool_specs 里已有的工具（如被过滤器清过）→ 补回。
        """
        added: list[str] = []
        reg = self.core.registry
        for spec in self._scan_plugins():
            name = spec.name
            owner = self._plugin_tool_names.get(name)
            if owner is None and reg.has(name):
                continue   # 与非插件工具重名：跳过，禁止插件覆盖内置工具
            # 同步 _all_tool_specs（list_tools 工具与 tool_filter 重建都以它为准）
            self._all_tool_specs = [
                s for s in self._all_tool_specs if s.name != name
            ] + [spec]
            if reg.has(name):
                reg._tools.pop(name)   # 插件工具热替换：先删旧再走正常注册（含校验）
            else:
                added.append(name)
            reg.register(spec)
            self._plugin_tool_names[name] = owner or "plugin"
        # registry 缺失补回（例如 tool_filter 白名单外清掉、但白名单现已放开）
        missing = [s for s in self._all_tool_specs if not reg.has(s.name)]
        if missing:
            reg.register_many(missing)
            added.extend(s.name for s in missing if s.name not in added)
        return added

    # --- 写入可观测（阶段A）：透传记忆层统计，不改写入行为 ---
    def reset_write_stats(self) -> None:
        """每轮对话开始前清零，使 last_write_stats 只反映本轮。"""
        if self.temporal_memory is not None and hasattr(self.temporal_memory, "reset_write_stats"):
            self.temporal_memory.reset_write_stats()

    def last_write_stats(self) -> dict[str, Any]:
        """本轮写入统计快照（calls/events/model/fallback/supplement）。

        无时间记忆层时返回全零——保持接口稳定，调用方不必判空。
        """
        if self.temporal_memory is not None and hasattr(self.temporal_memory, "last_write_stats"):
            return self.temporal_memory.last_write_stats()
        from yoai.temporal_memory import TemporalMemory
        return TemporalMemory._empty_write_stats()

    @staticmethod
    def _has_memory_worthy_fact(text: str) -> bool:
        """保守判定：一段用户话里是否有值得记忆的个人事实。

        只防"寒暄/提问被当事实记"，不做完整事实抽取（那是 remember_from_transcript 的事）。
        命中任一：第一人称事实陈述（I'm/I have/my.../我叫/我喜欢）、数字、明确偏好动词。
        """
        import re
        s = text.strip()
        # 中英文事实信号：第一人称所有格/亲属/偏好/居住/工作 + 中文数字（一二三…）。
        # 注意 \b 对中文无效（中文紧邻标点也算边界，但紧跟汉字时 \\b 会失效），故中文模式不用 \b。
        en = re.search(
            r"\b(I'm|I am|I have|I've|I like|I love|I prefer|I work|I live|I'm from|"
            r"my (name|birthday|favorite|favourite|job|home|family|cat|dog|car|hobby)|"
            r"remember that|keep in mind)\b", s, re.IGNORECASE)
        zh = re.search(
            r"(我叫|我(叫|是|有|在|喜欢|爱|住在|住|养|工作在|来自|生日|最爱|偏好|的家)|"
            r"我的(名字|生日|爱好|家人|猫|狗|车|工作|家)|记住|别忘了|请记)", s)
        # 阿拉伯数字或中文数字+亲属/物品量词（如"三个姐妹"）
        num = bool(re.search(r"\d", s)) or bool(re.search(
            r"[一二三四五六七八九十两]\s*(个|位|只|条|本|岁|姐妹|兄弟|孩子|猫|狗)", s))
        if not (en or zh or num):
            return False
        # 有明确事实信号时，短中文句（"我叫小明"）也算；无信号的长句仍需18字符防寒暄误记
        return len(s) >= 4

    async def astream(self, task: str):
        """驱动 Core 执行任务，逐条透出内核事件（不改动事件语义）。"""
        self.reset_write_stats()   # 旁路：本轮写入统计清零
        try:
            self.refresh_tools()   # 插件热加载（无 plugins 目录时零开销）
        except Exception:  # noqa: BLE001
            pass                   # 热加载失败不反噬主任务
        self._apply_tool_filter(task)
        final_text = ""

        # 流式增量（thinking / 文本 delta）由 provider 包装层暂存。Core 的 achat
        # 是"await 完才返回"的一次性接口——只有并发轮询才能在模型生成期间实时推 UI。
        # 起后台 poller 每 20ms drain outbox 到 queue；主循环同时消费 Core 事件与 queue。
        # 不改 Core 源码、不碰历史事件语义。
        extra_queue: asyncio.Queue[YoAiEvent] = asyncio.Queue()

        def _outbox_provider():
            """找带 outbox 的真实 provider：core.model 可能是 ExpertModelProvider
            等包装层，thinking/delta 存在其 .base 上（桌面生产路径就是如此）。"""
            node = getattr(self.core, "model", None)
            seen: set[int] = set()
            while node is not None and id(node) not in seen:
                seen.add(id(node))
                if callable(getattr(node, "drain_text", None)) or callable(
                    getattr(node, "drain_thinking", None)
                ):
                    return node
                # 桌面生产走 Suanli → GatewayModelProvider(adapter)，增量在 adapter 上
                next_node = getattr(node, "base", None) or getattr(node, "adapter", None)
                node = next_node
            return None

        def _drain_model_events() -> list[YoAiEvent]:
            try:
                model = _outbox_provider()
                out: list[YoAiEvent] = []
                drain_t = getattr(model, "drain_thinking", None)
                if callable(drain_t):
                    out.extend(YoAiEvent(_YoAiType("thinking"), {"text": t})
                               for t in drain_t() if t)
                drain_x = getattr(model, "drain_text", None)
                if callable(drain_x):
                    out.extend(YoAiEvent(_YoAiType("delta"), {"round": r, "text": t})
                               for r, t in drain_x() if t)
                return out
            except Exception:  # noqa: BLE001
                return []

        async def _poll_outbox() -> None:
            while True:
                for extra in _drain_model_events():
                    await extra_queue.put(extra)
                await asyncio.sleep(0.02)

        poller = asyncio.create_task(_poll_outbox())
        core_iter = self.core.astream(task).__aiter__()
        core_task: asyncio.Task | None = None
        queue_task: asyncio.Task | None = None
        try:
            while True:
                # 先清空已就绪的流式增量（实时性优先）
                while not extra_queue.empty():
                    yield extra_queue.get_nowait()
                if core_task is None:
                    core_task = asyncio.create_task(core_iter.__anext__())
                if queue_task is None:
                    queue_task = asyncio.create_task(extra_queue.get())
                done, _ = await asyncio.wait(
                    {core_task, queue_task}, return_when=asyncio.FIRST_COMPLETED
                )
                # 流式增量：取走后重建 task，core_task 不动（绝不取消，避免丢事件）
                if queue_task in done:
                    yield queue_task.result()
                    queue_task = asyncio.create_task(extra_queue.get())
                # Core 事件：取走后重建 task；StopAsyncIteration 表明事件流结束
                if core_task in done:
                    try:
                        event = core_task.result()
                    except StopAsyncIteration:
                        break
                    core_task = asyncio.create_task(core_iter.__anext__())
                    if event.type == EventType.DONE:
                        final_text = str((event.data or {}).get("final_text", ""))
                    yield event
        finally:
            for t in (core_task, queue_task):
                if t is not None and not t.done():
                    t.cancel()
            poller.cancel()
            try:
                await poller
            except asyncio.CancelledError:
                pass
            # 收尾兜底：最后事件后未 drain 的增量（异常收尾等），补发
            for extra in _drain_model_events():
                yield extra
        # 阶段B/C：确定性补充（均 opt-in，默认关闭；失败不能反噬主任务）
        if self.temporal_memory is None or not (self.memory_fallback or self.number_supplement):
            return
        turns = [{"role": "user", "content": task}]
        if final_text:
            turns.append({"role": "assistant", "content": final_text})
        # 阶段B：模型本轮一个都没记 + 用户话有事实信号 → 规则兜底
        if (self.memory_fallback
                and self.last_write_stats()["events"] == 0
                and self._has_memory_worthy_fact(task)):
            try:
                self.temporal_memory.remember_from_transcript(turns)
            except Exception:  # noqa: BLE001
                pass
        # 阶段C：无条件叠加数字事实（内部按 existing 去重，不重复写）
        if self.number_supplement:
            try:
                self.temporal_memory.supplement_number_facts(turns)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def is_done(event: Any) -> bool:
        """事件是否为任务完成。"""
        return event.type == EventType.DONE
