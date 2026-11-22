"""证据库：ExecutionEvidence 与 Attribution 的持久化。

复用 YoAi 既有模式：JSON 原子写 + 损坏隔离。
查询按样本类别 / 指纹 / 专家 / 父节点过滤，供样本隔离评测与三分归因消费。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from yoai.evidence.models import (
    SAMPLE_VALIDATION,
    Attribution,
    ExecutionEvidence,
)


class EvidenceStore:
    """执行证据与归因结论的落盘库。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._evidence: dict[str, dict[str, Any]] = {}
        self._attributions: dict[str, dict[str, Any]] = {}
        self._reports: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._evidence = raw.get("evidence", {})
                self._attributions = raw.get("attributions", {})
                self._reports = raw.get("reports", {})
        except (json.JSONDecodeError, OSError, ValueError):
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self._evidence, self._attributions = {}, {}
            self._reports = {}

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".yoai-evidence-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {"evidence": self._evidence, "attributions": self._attributions,
                     "reports": self._reports},
                    fh, ensure_ascii=False, indent=2, sort_keys=True,
                )
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, evidence: ExecutionEvidence) -> str:
        self._evidence[evidence.id] = evidence.to_dict()
        self._save()
        return evidence.id

    def get(self, evidence_id: str) -> ExecutionEvidence | None:
        d = self._evidence.get(evidence_id)
        return ExecutionEvidence.from_dict(d) if d else None

    def query(
        self,
        *,
        sample_class: str = "",
        task_fingerprint: str = "",
        expert_id: str = "",
        parent_id: str = "",
    ) -> list[ExecutionEvidence]:
        items = list(self._evidence.values())
        if sample_class:
            items = [e for e in items if e.get("sample_class") == sample_class]
        if task_fingerprint:
            items = [e for e in items if e.get("task_fingerprint") == task_fingerprint]
        if expert_id:
            items = [e for e in items if e.get("expert_id") == expert_id]
        if parent_id:
            items = [e for e in items if e.get("parent_id") == parent_id]
        return [ExecutionEvidence.from_dict(e) for e in items]

    def validation_set(self) -> list[ExecutionEvidence]:
        """隔离的验证样本（不得参与进化，只用于评测）。"""
        return self.query(sample_class=SAMPLE_VALIDATION)

    def add_attribution(self, attribution: Attribution) -> str:
        self._attributions[attribution.attribution_id] = attribution.to_dict()
        self._save()
        return attribution.attribution_id

    def attribution_for(self, evidence_id: str) -> Attribution | None:
        for d in self._attributions.values():
            if d.get("evidence_id") == evidence_id:
                return Attribution.from_dict(d)
        return None

    def add_evolution_report(self, report: dict[str, Any]) -> str:
        """持久化一份进化审计报告。"""
        rid = str(report.get("id", ""))
        self._reports[rid] = report
        self._save()
        return rid

    def evolution_reports(self) -> list[dict[str, Any]]:
        return list(self._reports.values())

    def latest(self) -> ExecutionEvidence | None:
        """最新一条证据（按写入顺序的最后一个 key）。"""
        if not self._evidence:
            return None
        last_id = list(self._evidence)[-1]
        return self.get(last_id)

    def count(self) -> int:
        return len(self._evidence)

    def status(self) -> dict[str, Any]:
        by_class: dict[str, int] = {}
        for e in self._evidence.values():
            c = e.get("sample_class", "")
            by_class[c] = by_class.get(c, 0) + 1
        return {"evidence": len(self._evidence), "attributions": len(self._attributions),
                "reports": len(self._reports), "by_class": by_class}
