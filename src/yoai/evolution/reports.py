"""进化报告持久化（YoAi 侧，内核零改动）。

EvolutionEngine.evolve() 返回 EvolutionReport；这里把每次尝试追加到独立 JSONL，
供桌面星图/评测复盘读取。损坏不致命，原子写。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


class EvolutionReportStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "evolution" / "reports.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._reports: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if isinstance(item, dict):
                        self._reports.append(item)
        except (OSError, ValueError):
            try:
                self.path.replace(self.path.with_suffix(".jsonl.corrupt"))
            except OSError:
                pass
            self._reports = []

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".evo-report-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for report in self._reports:
                    handle.write(json.dumps(report, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, report: dict[str, Any]) -> None:
        with self._lock:
            self._reports.append(report)
            self._save()

    def list(self, node_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            if not node_id:
                return [dict(r) for r in self._reports]
            return [dict(r) for r in self._reports if r.get("new_node_id") == node_id]
