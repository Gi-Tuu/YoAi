"""用户反馈信号持久化（RSI R0：只采集，不参与晋升）。

落盘 `<data_dir>/evidence/feedback.jsonl`，原子写、损坏隔离。
后续 R1 的能力边界看板从此处聚合，不反向污染执行证据。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from yoai.evidence.models import FeedbackSignal


class FeedbackStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "evidence" / "feedback.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._signals: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if isinstance(item, dict):
                        self._signals.append(item)
        except (OSError, ValueError):
            try:
                self.path.replace(self.path.with_suffix(".jsonl.corrupt"))
            except OSError:
                pass
            self._signals = []

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".feedback-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for item in self._signals:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, signal: FeedbackSignal) -> str:
        with self._lock:
            self._signals.append(signal.to_dict())
            self._save()
        return signal.id

    def list(self, *, evidence_id: str = "", kind: str = "") -> list[FeedbackSignal]:
        with self._lock:
            items = self._signals
            if evidence_id:
                items = [i for i in items if i.get("evidence_id") == evidence_id]
            if kind:
                items = [i for i in items if i.get("kind") == kind]
            return [FeedbackSignal.from_dict(i) for i in items]

    def count(self) -> int:
        with self._lock:
            return len(self._signals)
