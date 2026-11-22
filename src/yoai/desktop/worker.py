"""桌面端异步工作线程：在后台 asyncio 循环里驱动 YoAiAgent.astream。

Qt 主线程只负责渲染，Core 的事件流通过 Signal 回传，避免阻塞 UI。
"""

from __future__ import annotations

import asyncio
from typing import Any

from PySide6.QtCore import QThread, Signal

from yoai.agent import YoAiAgent


class AgentWorker(QThread):
    """一次任务一个 worker；事件逐条发出，完成时发 finished。"""

    event_received = Signal(str, dict)   # event_type(str), data(dict)
    task_done = Signal(str)              # final_text
    task_error = Signal(str)

    def __init__(
        self, agent: YoAiAgent, task: str, parent=None,
        *, evidence_store=None, evidence_meta=None,
    ) -> None:
        super().__init__(parent)
        self._agent = agent
        self._task = task
        self._evidence_store = evidence_store
        self._evidence_meta = evidence_meta or {}

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            asyncio.run(self._consume())
        except Exception as exc:  # noqa: BLE001 - 线程内必须兜住，不能让 UI 卡死
            self.task_error.emit(f"{type(exc).__name__}: {exc}")

    async def _consume(self) -> None:
        from yoai.evidence import ExecutionEvidenceCollector, AttributionEngine

        collector = ExecutionEvidenceCollector() if self._evidence_store else None
        final_text = ""
        async for event in self._agent.astream(self._task):
            if collector is not None:
                collector.observe(event)
            self.event_received.emit(event.type.value, dict(event.data))
            if event.type.value == "done":
                final_text = str(event.data.get("final_text", ""))
        # 证据落盘（旁路，失败不影响任务结果）
        if collector is not None and self._evidence_store is not None:
            try:
                meta = self._evidence_meta
                provider = meta.get("model_provider")
                usage_override = getattr(provider, "total_usage", None) if provider else None
                # 真实专家身份：从 ExpertModelProvider 的本次路由决策读取（不是假填）
                expert_id = meta.get("expert_id")
                parent_id = meta.get("parent_id")
                decision = None
                if provider is not None and hasattr(provider, "last_decision"):
                    decision = getattr(provider, "last_decision", None)
                    expert_id = getattr(provider, "last_expert_id", None) or expert_id
                    get_parent = getattr(provider, "last_parent_id", None)
                    parent_id = get_parent if get_parent is not None else parent_id
                evidence = collector.finish(
                    session_id=meta.get("session_id", ""),
                    task=self._task,
                    task_fingerprint=meta.get("task_fingerprint", ""),
                    fingerprint_tags=tuple(meta.get("fingerprint_tags", ())),
                    sample_class=meta.get("sample_class", "evolution"),
                    expert_id=expert_id,
                    parent_id=parent_id,
                    usage_override=usage_override,
                    route_decision=decision.to_dict() if decision else None,
                )
                self._evidence_store.add(evidence)
                attribution = AttributionEngine(self._evidence_store).attribute(evidence)
                self._evidence_store.add_attribution(attribution)
            except Exception:  # noqa: BLE001 - 证据旁路不得反噬任务
                pass
        self.task_done.emit(final_text)
