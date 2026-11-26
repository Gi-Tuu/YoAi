"""R3.2 试用与批准控制层（YoAi 侧，内核零改动）。

只管理 trial 元数据、试用证据聚合、硬门槛判定与批准/拒绝动作。
实际路由到 probation 由 ExpertRouter 的 trial scope 处理；本模块不碰 Core。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from yoai.evidence.benchmark_lab import wilson_interval
from yoai.evidence.feedback import FeedbackStore
from yoai.evidence.models import SAMPLE_TRIAL
from yoai.evidence.store import EvidenceStore
from yoai.evolution.archive import EvolutionArchive
from yoai.evolution.reports import EvolutionReportStore

MIN_TRIAL_SAMPLES = 20
MAX_TRIAL_SAMPLES = 50
MAX_COST_RATIO = 1.20
MAX_REWORK_DELTA = 0.05
MAX_REWORK_ABSOLUTE = 0.20
CI_TOLERANCE = 0.05
RATE_TOLERANCE = 0.02


@dataclass
class TrialRecord:
    id: str
    node_id: str
    parent_id: str
    primary_tag: str
    scope: str
    max_n: int = MIN_TRIAL_SAMPLES
    status: str = "running"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = ""
    decision: str = ""
    decided_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrialRecord":
        return cls(
            id=str(d.get("id", uuid.uuid4().hex[:12])),
            node_id=str(d.get("node_id", "")),
            parent_id=str(d.get("parent_id", "")),
            primary_tag=str(d.get("primary_tag", "")),
            scope=str(d.get("scope", "")),
            max_n=int(d.get("max_n", MIN_TRIAL_SAMPLES)),
            status=str(d.get("status", "running")),
            created_at=str(d.get("created_at", datetime.now(timezone.utc).isoformat())),
            expires_at=str(d.get("expires_at", "")),
            decision=str(d.get("decision", "")),
            decided_by=str(d.get("decided_by", "")),
        )


@dataclass
class TrialReport:
    trial_id: str
    node_id: str
    parent_id: str
    passed: bool
    reason: str
    child_samples: int
    parent_samples: int
    child_rate: float
    parent_rate: float
    child_ci: list[float]
    parent_ci: list[float]
    child_rework: float
    parent_rework: float
    child_tokens: int
    parent_tokens: int
    verified_failures: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrialStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "evolution" / "trials.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if isinstance(item, dict):
                        self._items.append(item)
        except (OSError, ValueError):
            try:
                self.path.replace(self.path.with_suffix(".jsonl.corrupt"))
            except OSError:
                pass
            self._items = []

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".trial-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for item in self._items:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, record: TrialRecord) -> None:
        with self._lock:
            self._items.append(record.to_dict())
            self._save()

    def update(self, trial_id: str, **changes: Any) -> TrialRecord | None:
        with self._lock:
            for item in self._items:
                if item.get("id") == trial_id:
                    item.update(changes)
                    self._save()
                    return TrialRecord.from_dict(item)
        return None

    def get(self, trial_id: str) -> TrialRecord | None:
        with self._lock:
            for item in self._items:
                if item.get("id") == trial_id:
                    return TrialRecord.from_dict(item)
        return None

    def list(self, *, node_id: str = "", status: str = "") -> list[TrialRecord]:
        with self._lock:
            items = self._items
            if node_id:
                items = [i for i in items if i.get("node_id") == node_id]
            if status:
                items = [i for i in items if i.get("status") == status]
            return [TrialRecord.from_dict(i) for i in items]


class TrialController:
    def __init__(
        self,
        archive: EvolutionArchive,
        evidence_store: EvidenceStore,
        feedback_store: FeedbackStore,
        report_store: EvolutionReportStore,
        trial_store: TrialStore,
    ) -> None:
        self.archive = archive
        self.store = evidence_store
        self.feedback = feedback_store
        self.reports = report_store
        self.trials = trial_store

    def start(self, node_id: str, scope: str, max_n: int = MIN_TRIAL_SAMPLES) -> TrialRecord:
        node = self.archive.get(node_id)
        if node is None or node.lifecycle != "probation":
            raise ValueError("仅 probation 节点可开始试用")
        if not scope or ":" not in scope:
            raise ValueError("scope 需为 session:<id> 或 tag:<tag>")
        running = self.trials.list(node_id=node_id, status="running")
        if running:
            raise ValueError("该节点已有运行中的试用")
        max_n = max(MIN_TRIAL_SAMPLES, min(MAX_TRIAL_SAMPLES, int(max_n)))
        tag = str(node.diff.get("tag", "") or (node.spec.capability_tags or ("general",))[0])
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        record = TrialRecord(
            id=uuid.uuid4().hex[:12], node_id=node_id,
            parent_id=node.parent_id or "", primary_tag=tag,
            scope=str(scope), max_n=max_n,
            expires_at=expires.isoformat(),
        )
        self.trials.add(record)
        self.reports.add({"id": f"trial-start-{record.id}", "evidence_id": "",
                          "triggered": True, "cause": "rsi_trial_start",
                          "new_node_id": node_id, "reason": f"试用 {scope}，上限 {max_n}",
                          "created_at": record.created_at, "kind": "rsi_trial",
                          "trial_id": record.id})
        return record

    def stop(self, trial_id: str, reason: str = "") -> TrialRecord | None:
        return self.trials.update(trial_id, status="stopped", decision=reason)

    def report(self, trial_id: str) -> TrialReport:
        record = self.trials.get(trial_id)
        if record is None:
            raise ValueError("试用不存在")
        items = [e for e in self.store.query(sample_class=SAMPLE_TRIAL)
                 if e.trial_id == trial_id]
        child = [e for e in items if e.trial_role == "child"]
        parent = [e for e in items if e.trial_role == "parent"]
        tag = record.primary_tag

        def ok_count(rows):
            return sum(1 for e in rows
                       if (e.verification or {}).get("status") == "verified_success")
        def rework_count(rows):
            negatives = {s.evidence_id for s in self.feedback.list() if s.polarity < 0}
            return sum(1 for e in rows if e.id in negatives)
        def tokens(rows):
            return int(sum(int(e.usage.get("total_tokens", 0) or 0) for e in rows) / len(rows)) if rows else 0

        c_n, p_n = len(child), len(parent)
        c_ok, p_ok = ok_count(child), ok_count(parent)
        c_rate = c_ok / c_n if c_n else 0.0
        p_rate = p_ok / p_n if p_n else 0.0
        c_ci = list(wilson_interval(c_ok, c_n)) if c_n else [0.0, 0.0]
        p_ci = list(wilson_interval(p_ok, p_n)) if p_n else [0.0, 0.0]
        c_rework = rework_count(child) / c_n if c_n else 0.0
        p_rework = rework_count(parent) / p_n if p_n else 0.0
        c_tokens, p_tokens = tokens(child), tokens(parent)
        failures = sum(1 for e in child
                       if (e.verification or {}).get("status") == "verified_failure")

        reasons = []
        if c_n < MIN_TRIAL_SAMPLES or p_n < MIN_TRIAL_SAMPLES:
            reasons.append(f"样本不足：child={c_n} parent={p_n}（需各≥{MIN_TRIAL_SAMPLES}）")
        if c_rate < p_rate - RATE_TOLERANCE:
            reasons.append(f"成功率下降：child={c_rate:.1%} parent={p_rate:.1%}")
        if c_ci[0] < p_ci[0] - CI_TOLERANCE:
            reasons.append("成功率置信下界低于父节点超过 5pp")
        if c_rework > min(p_rework + MAX_REWORK_DELTA, MAX_REWORK_ABSOLUTE):
            reasons.append(f"返工率过高：child={c_rework:.1%} parent={p_rework:.1%}")
        if failures:
            reasons.append(f"verified_failure={failures}")
        if p_tokens <= 0 or c_tokens > p_tokens * MAX_COST_RATIO:
            reasons.append(f"成本守卫未通过：child={c_tokens} parent={p_tokens}")

        return TrialReport(
            trial_id=trial_id, node_id=record.node_id, parent_id=record.parent_id,
            passed=not reasons and tag in {t for e in child for t in e.fingerprint_tags},
            reason="；".join(reasons) or "试用硬门槛全部通过",
            child_samples=c_n, parent_samples=p_n, child_rate=c_rate, parent_rate=p_rate,
            child_ci=c_ci, parent_ci=p_ci, child_rework=c_rework, parent_rework=p_rework,
            child_tokens=c_tokens, parent_tokens=p_tokens, verified_failures=failures,
        )

    def approve(self, trial_id: str, approved_by: str, reason: str = "") -> TrialReport:
        record = self.trials.get(trial_id)
        if record is None or record.status != "running":
            raise ValueError("只有运行中的试用可批准")
        if not approved_by.strip():
            raise ValueError("人工批准必须记录批准人")
        report = self.report(trial_id)
        if not report.passed:
            raise ValueError(f"试用未通过硬门槛：{report.reason}")
        node = self.archive.get(record.node_id)
        if node is None or node.lifecycle != "probation":
            raise ValueError("节点不在 probation 状态")
        self.archive.transition(record.node_id, "active")
        self.trials.update(trial_id, status="approved", decision=reason,
                           decided_by=approved_by)
        self.reports.add({"id": f"approval-{trial_id}", "evidence_id": "",
                          "triggered": True, "cause": "rsi_approval",
                          "new_node_id": record.node_id,
                          "reason": f"批准人 {approved_by}：{reason or report.reason}",
                          "created_at": datetime.now(timezone.utc).isoformat(),
                          "kind": "rsi_approval", "trial_id": trial_id,
                          "report": report.to_dict()})
        return report

    def reject(self, trial_id: str, reason: str = "") -> TrialRecord | None:
        record = self.trials.get(trial_id)
        if record is None or record.status != "running":
            raise ValueError("只有运行中的试用可拒绝")
        node = self.archive.get(record.node_id)
        if node and node.lifecycle == "probation":
            self.archive.transition(record.node_id, "retired")
        updated = self.trials.update(trial_id, status="rejected", decision=reason,
                                     decided_by="approval")
        self.reports.add({"id": f"reject-{trial_id}", "evidence_id": "",
                          "triggered": True, "cause": "rsi_approval_reject",
                          "new_node_id": record.node_id, "reason": reason or "试用被拒绝",
                          "created_at": datetime.now(timezone.utc).isoformat(),
                          "kind": "rsi_approval", "trial_id": trial_id})
        return updated
