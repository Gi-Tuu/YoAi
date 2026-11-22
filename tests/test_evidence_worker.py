"""AgentWorker 自动证据采集测试（offscreen）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:/Competition/YAI Agent Core") / "src"))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from yai_core import ModelResponse, ScriptedModel  # noqa: E402

from yoai.agent import YoAiAgent  # noqa: E402
from yoai.desktop.worker import AgentWorker  # noqa: E402
from yoai.evidence import EvidenceStore  # noqa: E402


def test_worker_auto_saves_evidence(tmp_path):
    qapp = QApplication.instance() or QApplication([])
    store = EvidenceStore(tmp_path / "e.json")
    agent = YoAiAgent(model=ScriptedModel([ModelResponse(content="回答")]), data_dir=tmp_path)
    worker = AgentWorker(
        agent, "记住我的城市", None,
        evidence_store=store,
        evidence_meta={
            "session_id": "s1", "task_fingerprint": "k1",
            "fingerprint_tags": ("memory",), "sample_class": "evolution",
            "expert_id": "root", "parent_id": None,
        },
    )
    loop = QEventLoop()
    timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(5000)
    worker.task_done.connect(lambda _: loop.quit())
    worker.start()
    loop.exec(); timer.stop(); worker.wait(2000)

    assert store.count() == 1
    ev = store.query(task_fingerprint="k1")[0]
    assert ev.session_id == "s1" and ev.sample_class == "evolution"
    assert store.attribution_for(ev.id) is not None
