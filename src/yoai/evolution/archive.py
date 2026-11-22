"""进化档案 · M0。

职责：保存专家节点、版本血统、生命周期状态、恢复点与历史证据索引。
零第三方依赖、JSON 原子写、损坏文件隔离（复用 Context/Goals/ChatStore 的模式）。

边界（见 docs/EVOLUTION-PLAN.md）：
- 只存"能力切面"配置，不存人格/记忆/会话历史。
- 父节点产生子节点后仍保持原状态、仍可参与路由。
- retired 为终态；恢复走 restore() 生成新的 candidate 节点，不复活。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from yoai.evolution.models import (
    Checkpoint,
    EvidenceRef,
    ExpertNode,
    ExpertSpec,
    Lifecycle,
)


class EvolutionArchive:
    """进化树档案：节点的增删改查、血统、状态机、恢复。"""

    def __init__(self, path: str | Path, *, dependencies: dict[str, str] | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._nodes: dict[str, ExpertNode] = {}
        self._root_id: str | None = None
        self._next_version = 1
        self.default_dependencies = dict(dependencies or {})
        self._load()

    # --- 持久化 ---
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            self._nodes = {
                k: ExpertNode.from_dict(v)
                for k, v in raw.get("nodes", {}).items()
                if isinstance(v, dict)
            }
            self._root_id = raw.get("root_id")
            self._next_version = int(raw.get("next_version", 1))
        except (json.JSONDecodeError, OSError, ValueError, KeyError):
            # 损坏不静默覆盖：改名隔离，空档案重启
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self._nodes, self._root_id, self._next_version = {}, None, 1

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".yoai-evo-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "root_id": self._root_id,
                        "next_version": self._next_version,
                        "nodes": {k: v.to_dict() for k, v in self._nodes.items()},
                    },
                    fh, ensure_ascii=False, indent=2, sort_keys=True,
                )
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # --- 版本 ---
    def _bump_version(self) -> int:
        v = self._next_version
        self._next_version += 1
        return v

    # --- 建根 / 生子 ---
    def create_root(self, name: str, spec: ExpertSpec) -> ExpertNode:
        """创建根节点（active，作为通用回退点）。已有根则复用，不重建。"""
        if self._root_id and self._root_id in self._nodes:
            return self._nodes[self._root_id]
        root = ExpertNode.create(
            name, self._bump_version(), spec,
            lifecycle="active",
            dependencies=dict(self.default_dependencies),
            diff={},
        )
        self._nodes[root.id] = root
        self._root_id = root.id
        self._save()
        return root

    @property
    def root(self) -> ExpertNode | None:
        return self._nodes.get(self._root_id) if self._root_id else None

    def create_child(
        self,
        parent_id: str,
        name: str,
        spec: ExpertSpec,
        *,
        diff: dict[str, Any] | None = None,
        dependencies: dict[str, str] | None = None,
    ) -> ExpertNode:
        """从父节点派生一个 candidate 子节点；父节点状态不变、仍可路由。"""
        parent = self._nodes.get(parent_id)
        if not parent:
            raise KeyError(f"父节点不存在：{parent_id}")
        deps = dict(parent.dependencies)
        deps.update(dependencies or {})
        child = ExpertNode.create(
            name, self._bump_version(), spec,
            parent_id=parent_id, diff=diff,
            dependencies=deps, lifecycle="candidate",
        )
        self._nodes[child.id] = child
        self._save()
        return child

    # --- 查询 ---
    def get(self, node_id: str) -> ExpertNode | None:
        return self._nodes.get(node_id)

    def list_nodes(
        self, *, lifecycle: Lifecycle | str = "", capability_tag: str = ""
    ) -> list[ExpertNode]:
        nodes = list(self._nodes.values())
        if lifecycle:
            nodes = [n for n in nodes if n.lifecycle == lifecycle]
        if capability_tag:
            nodes = [n for n in nodes if capability_tag in n.spec.capability_tags]
        return sorted(nodes, key=lambda n: n.version)

    def routing_candidates(self, capability_tag: str = "") -> list[ExpertNode]:
        """可参与路由的节点：仅 active（retired/candidate/probation 不参与）。"""
        return self.list_nodes(lifecycle="active", capability_tag=capability_tag)

    def children(self, node_id: str) -> list[ExpertNode]:
        return [n for n in self._nodes.values() if n.parent_id == node_id]

    def lineage(self, node_id: str) -> list[ExpertNode]:
        """从根到该节点的祖先链（含自身）。"""
        chain: list[ExpertNode] = []
        node = self._nodes.get(node_id)
        seen: set[str] = set()
        while node and node.id not in seen:
            seen.add(node.id)
            chain.append(node)
            node = self._nodes.get(node.parent_id) if node.parent_id else None
        return list(reversed(chain))

    def descendants(self, node_id: str) -> list[ExpertNode]:
        """所有后代（不含自身）。"""
        out: list[ExpertNode] = []
        frontier = [node_id]
        seen: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            for child in self.children(current):
                out.append(child)
                frontier.append(child.id)
        return sorted(out, key=lambda n: n.version)

    # --- 生命周期 ---
    def transition(self, node_id: str, target: Lifecycle | str) -> bool:
        node = self._nodes.get(node_id)
        if not node or not node.can_transition(target):
            return False
        node.transition(target)  # type: ignore[arg-type]
        self._save()
        return True

    def add_evidence(self, node_id: str, evidence: EvidenceRef) -> bool:
        node = self._nodes.get(node_id)
        if not node:
            return False
        node.add_evidence(evidence)
        self._save()
        return True

    # --- 恢复 ---
    def checkpoint(self, node_id: str) -> Checkpoint | None:
        node = self._nodes.get(node_id)
        return node.checkpoint() if node else None

    def restore(
        self, node_id: str, *, name: str | None = None
    ) -> ExpertNode | None:
        """从旧节点的恢复点生成一个**新的 candidate 节点**，保留血统。

        不复活 retired 节点（retired 为终态）；新节点的 parent 指向被恢复节点。
        """
        original = self._nodes.get(node_id)
        if not original:
            return None
        cp = original.checkpoint()
        child = ExpertNode.create(
            name or f"{cp.name} (恢复)", self._bump_version(), cp.spec,
            parent_id=cp.node_id,
            diff={"restored_from": cp.node_id, "restored_version": cp.version},
            dependencies=dict(cp.dependencies),
            lifecycle="candidate",
        )
        self._nodes[child.id] = child
        self._save()
        return child

    # --- 统计 ---
    def count(self) -> int:
        return len(self._nodes)

    def status(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for node in self._nodes.values():
            result[node.lifecycle] = result.get(node.lifecycle, 0) + 1
        return result
