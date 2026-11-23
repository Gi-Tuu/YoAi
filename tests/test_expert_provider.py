"""ExpertModelProvider 测试：真路由、提示注入、expert/parent 暴露、usage 转发。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yai_core.types import ModelResponse  # noqa: E402

from yoai.evolution import EvolutionArchive, ExpertRouter, ExpertSpec  # noqa: E402
from yoai.models import ExpertModelProvider  # noqa: E402


class FakeBase:
    yai_multimodal = False

    def __init__(self) -> None:
        self.seen = None
        self.total_usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}

    async def achat(self, messages, tools=None, *, tier="standard"):
        self.seen = messages
        return ModelResponse(content="回答")


def _setup(tmp_path):
    ar = EvolutionArchive(tmp_path / "evo.json")
    root = ar.create_root("root", ExpertSpec())
    writer = ar.create_child(
        root.id, "写作专家",
        ExpertSpec(prompt_suffix="写作要点：先列大纲", capability_tags=("writing",)),
    )
    ar.transition(writer.id, "probation")
    ar.transition(writer.id, "active")
    return ar, root, writer


def test_provider_routes_and_injects(tmp_path):
    ar, root, writer = _setup(tmp_path)
    base = FakeBase()
    provider = ExpertModelProvider(base, ExpertRouter(ar), ar)

    resp = asyncio.run(provider.achat([
        {"role": "system", "content": "你是 YoAi"},
        {"role": "user", "content": "帮我写一篇总结"},
    ]))
    assert resp.content == "回答"
    # 真路由选中写作专家
    assert provider.last_expert_id == writer.id
    assert provider.last_parent_id == root.id
    # 提示词片段真注入到 system
    assert any("写作要点：先列大纲" in str(m.get("content", "")) for m in base.seen)
    # 决策可审计
    assert provider.last_decision.to_dict()["selected_id"] == writer.id


def test_provider_no_system_inserts_one(tmp_path):
    ar, root, writer = _setup(tmp_path)
    base = FakeBase()
    provider = ExpertModelProvider(base, ExpertRouter(ar), ar)
    asyncio.run(provider.achat([{"role": "user", "content": "写文案"}]))
    assert base.seen[0]["role"] == "system"


def test_provider_fallback_root_has_no_parent(tmp_path):
    ar, root, writer = _setup(tmp_path)
    base = FakeBase()
    provider = ExpertModelProvider(base, ExpertRouter(ar), ar)
    asyncio.run(provider.achat([{"role": "user", "content": "你好"}]))
    assert provider.last_expert_id == root.id
    assert provider.last_parent_id is None  # 根节点无父


def test_provider_forwards_usage(tmp_path):
    ar, root, writer = _setup(tmp_path)
    provider = ExpertModelProvider(FakeBase(), ExpertRouter(ar), ar)
    assert provider.total_usage["total_tokens"] == 3


def test_describe_shows_decision(tmp_path):
    ar, root, writer = _setup(tmp_path)
    provider = ExpertModelProvider(FakeBase(), ExpertRouter(ar), ar)
    asyncio.run(provider.achat([{"role": "user", "content": "写摘要"}]))
    d = provider.describe()
    assert d["expert_id"] == writer.id and d["decision"]["reason"]


def test_worker_records_expert_id_from_provider(tmp_path):
    """关键闭环：worker 落盘证据时 expert_id 来自真实路由决策。"""
    from yai_core import ScriptedModel
    from yoai.agent import YoAiAgent
    from yoai.desktop.worker import AgentWorker
    from yoai.evidence import EvidenceStore
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    ar, root, writer = _setup(tmp_path / "evo")
    base = ScriptedModel([ModelResponse(content="回答")])
    provider = ExpertModelProvider(base, ExpertRouter(ar), ar)
    agent = YoAiAgent(model=provider, data_dir=tmp_path)
    store = EvidenceStore(tmp_path / "ev.json")
    worker = AgentWorker(
        agent, "帮我写一篇总结", None,
        evidence_store=store,
        evidence_meta={
            "session_id": "s", "task_fingerprint": "k",
            "fingerprint_tags": ("writing",), "sample_class": "evolution",
            "expert_id": None, "parent_id": None, "model_provider": provider,
        },
    )
    loop = QEventLoop()
    timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(5000)
    worker.task_done.connect(lambda _: loop.quit())
    worker.start(); loop.exec(); timer.stop(); worker.wait(2000)

    ev = store.query(task_fingerprint="k")[0]
    assert ev.expert_id == writer.id          # 真实专家 id 落盘
    assert ev.parent_id == root.id            # 父节点 id 落盘（对照评测用）
    assert ev.route_decision is not None
    assert ev.route_decision["selected_id"] == writer.id
