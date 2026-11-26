"""R4 元策略：进化规则本身的版本化与受控改进（YoAi 侧，Core 零改动）。

元策略只管阈值/权重；安全边界（审计、回滚、人工批准）不能被元策略改写。
新版本默认 candidate，必须人工批准才 active。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yoai.evolution.reports import EvolutionReportStore


@dataclass
class MetaPolicy:
    version: int
    parent_id: str = ""
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    min_validation_samples: int = 5
    min_trial_samples: int = 20
    weak_gap: float = 0.10
    watch_gap: float = 0.05
    weak_rework: float = 0.25
    watch_rework: float = 0.15
    cost_ratio: float = 1.20
    cooldown_days: int = 7
    capability_ratio: float = 0.60
    environment_ratio: float = 0.20

    @property
    def id(self) -> str:
        return f"meta-v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MetaPolicy":
        fields = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**fields)


class MetaPolicyStore:
    def __init__(self, data_dir: str | Path) -> None:
        root = Path(data_dir) / "evolution"
        self.path = root / "meta_policies.jsonl"
        self.active_path = root / "meta_active.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._policies: list[MetaPolicy] = []
        self._load()
        if not self._policies:
            self.add(MetaPolicy(version=1, reason="初始元策略"))
            self.set_active(1)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._policies.append(MetaPolicy.from_dict(json.loads(line)))
        except (OSError, ValueError):
            self._policies = []

    def _save(self) -> None:
        self.path.write_text("\n".join(
            json.dumps(p.to_dict(), ensure_ascii=False) for p in self._policies) + "\n",
            encoding="utf-8")

    def add(self, policy: MetaPolicy) -> MetaPolicy:
        with self._lock:
            self._policies = [p for p in self._policies if p.version != policy.version]
            self._policies.append(policy)
            self._policies.sort(key=lambda p: p.version)
            self._save()
        return policy

    def list(self) -> list[MetaPolicy]:
        with self._lock:
            return list(self._policies)

    def get(self, version: int) -> MetaPolicy | None:
        return next((p for p in self.list() if p.version == version), None)

    def set_active(self, version: int) -> MetaPolicy:
        policy = self.get(version)
        if policy is None:
            raise ValueError(f"元策略版本不存在：{version}")
        self.active_path.write_text(json.dumps({"active": version}, ensure_ascii=False),
                                    encoding="utf-8")
        return policy

    def active(self) -> MetaPolicy:
        version = 1
        if self.active_path.exists():
            try:
                version = int(json.loads(self.active_path.read_text(encoding="utf-8")).get("active", 1))
            except (ValueError, OSError):
                version = 1
        return self.get(version) or self.list()[0]


class MetaEvolution:
    def __init__(self, store: MetaPolicyStore, reports: EvolutionReportStore) -> None:
        self.store = store
        self.reports = reports

    def status(self) -> dict[str, Any]:
        active = self.store.active()
        return {"active": active.to_dict(),
                "versions": [p.to_dict() for p in self.store.list()]}

    def propose(self) -> dict[str, Any]:
        active = self.store.active()
        items = self.reports.list()
        promotions = [r for r in items if r.get("kind") == "r3_promotion"]
        rollbacks = [r for r in items if r.get("kind") == "rsi_rollback"]
        improved = [r for r in items if r.get("kind") == "rsi_validation"
                    and r.get("verdict") == "improved"]

        next_version = max(p.version for p in self.store.list()) + 1
        reason = ""
        changes: dict[str, Any] = {}
        if rollbacks and len(rollbacks) / max(1, len(promotions)) > 0.3:
            reason = "回滚率偏高，收紧晋升门槛"
            changes = {
                "weak_gap": min(0.25, round(active.weak_gap + 0.02, 4)),
                "cost_ratio": max(1.0, round(active.cost_ratio - 0.05, 4)),
                "weak_rework": max(0.10, round(active.weak_rework - 0.02, 4)),
            }
        elif len(improved) >= 3 and not promotions and active.min_trial_samples > 8:
            reason = "多次隔离验证 improved 但无晋升，适度放宽 trial 样本要求"
            changes = {
                "min_trial_samples": max(8, active.min_trial_samples - 2),
                "weak_gap": max(0.05, round(active.weak_gap - 0.01, 4)),
            }
        else:
            return {"created": False,
                    "reason": f"证据不足或无需调整（promotions={len(promotions)}, "
                              f"rollbacks={len(rollbacks)}, improved={len(improved)}）"}

        payload = active.to_dict()
        payload.pop("created_at", None)
        payload.update(changes)
        payload.update({"version": next_version, "parent_id": active.id,
                        "reason": reason, "created_at": datetime.now(timezone.utc).isoformat()})
        proposed = MetaPolicy.from_dict(payload)
        self.store.add(proposed)
        self.reports.add({
            "id": f"meta-propose-{proposed.id}", "evidence_id": "",
            "triggered": True, "cause": "rsi_meta_propose",
            "new_node_id": proposed.id, "reason": reason,
            "created_at": proposed.created_at, "kind": "rsi_meta_propose",
            "changes": changes,
        })
        return {"created": True, "policy": proposed.to_dict(), "reason": reason}

    def approve(self, version: int, approved_by: str) -> MetaPolicy:
        if not approved_by.strip():
            raise ValueError("元策略批准必须记录批准人")
        policy = self.store.set_active(version)
        self.reports.add({
            "id": f"meta-approve-{policy.id}", "evidence_id": "",
            "triggered": True, "cause": "rsi_meta_approve",
            "new_node_id": policy.id,
            "reason": f"批准人 {approved_by} 激活元策略 v{version}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "rsi_meta_approve",
        })
        return policy
