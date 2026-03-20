"""Generic DAG engine utilities used by pipeline orchestration.

This module is analysis/orchestration infrastructure only. It does not
perform any market decisioning and does not alter Layer-12 authority.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class DagEdge:
    """Directed edge from dependency -> dependent."""

    source: str
    target: str


class DagCycleError(ValueError):
    """Raised when a graph with cycles is topologically sorted."""


class DagEngine:
    """Simple directed-acyclic graph helper.

    Nodes are represented as case-sensitive string IDs.
    """

    def __init__(self) -> None:
        self._nodes: set[str] = set()
        self._outgoing: dict[str, set[str]] = {}
        self._incoming: dict[str, set[str]] = {}

    def add_node(self, node: str) -> None:
        node_id = str(node).strip()
        if not node_id:
            raise ValueError("node must be non-empty")
        if node_id in self._nodes:
            return
        self._nodes.add(node_id)
        self._outgoing[node_id] = set()
        self._incoming[node_id] = set()

    def add_edge(self, source: str, target: str) -> None:
        src = str(source).strip()
        dst = str(target).strip()
        if not src or not dst:
            raise ValueError("edge endpoints must be non-empty")
        self.add_node(src)
        self.add_node(dst)
        if dst in self._outgoing[src]:
            return
        self._outgoing[src].add(dst)
        self._incoming[dst].add(src)

    def topological_sort(self) -> list[str]:
        """Return stable topological order or raise DagCycleError."""
        incoming = {node: set(parents) for node, parents in self._incoming.items()}
        ready = deque(sorted(node for node in self._nodes if not incoming[node]))
        order: list[str] = []

        while ready:
            node = ready.popleft()
            order.append(node)
            for child in sorted(self._outgoing.get(node, ())):
                incoming[child].discard(node)
                if not incoming[child]:
                    ready.append(child)

        if len(order) != len(self._nodes):
            remaining = sorted(node for node in self._nodes if node not in order)
            raise DagCycleError(f"cycle detected in DAG nodes: {remaining}")
        return order

    def execution_batches(self) -> list[list[str]]:
        """Return layers grouped by topological level for parallel execution."""
        incoming_counts = {node: len(parents) for node, parents in self._incoming.items()}
        ready = sorted(node for node, count in incoming_counts.items() if count == 0)
        batches: list[list[str]] = []
        processed = 0

        while ready:
            current_batch = sorted(ready)
            batches.append(current_batch)
            ready = []
            for node in current_batch:
                processed += 1
                for child in sorted(self._outgoing.get(node, ())):
                    incoming_counts[child] -= 1
                    if incoming_counts[child] == 0:
                        ready.append(child)

        if processed != len(self._nodes):
            remaining = sorted(node for node in self._nodes if incoming_counts[node] > 0)
            raise DagCycleError(f"cycle detected in DAG nodes: {remaining}")
        return batches

    def dependencies_for(self, node: str) -> list[str]:
        """Return sorted direct dependencies for a node."""
        node_id = str(node).strip()
        if node_id not in self._nodes:
            return []
        return sorted(self._incoming.get(node_id, ()))

    def to_edge_list(self) -> list[DagEdge]:
        """Return all directed edges in stable order."""
        edges: list[DagEdge] = []
        for source in sorted(self._nodes):
            for target in sorted(self._outgoing.get(source, ())):
                edges.append(DagEdge(source=source, target=target))
        return edges
