"""State store: persisted desired + observed state.

JSON-file-backed here for a runnable local demo. In production this is etcd /
Spanner / a relational DB. The important properties we model:

- single place that holds both clusters (desired) and nodes (observed),
- optimistic concurrency via a monotonically increasing revision,
- crash-safety: the reconciler keeps no important state in memory, so it can be
  restarted and resume from the store.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Iterable

from .models import Cluster, Node, NodePool, NodeState, ClusterState


class Store:
    def __init__(self, path: str | None = None):
        self._path = path
        self._lock = threading.RLock()
        self.clusters: dict[str, Cluster] = {}
        self.nodes: dict[str, Node] = {}
        self.revision: int = 0
        if path and os.path.exists(path):
            self.load()

    # ---- mutation -------------------------------------------------------
    def put_cluster(self, cluster: Cluster) -> None:
        with self._lock:
            self.clusters[cluster.name] = cluster
            self._bump()

    def put_node(self, node: Node) -> None:
        with self._lock:
            self.nodes[node.id] = node
            self._bump()

    def remove_node(self, node_id: str) -> None:
        with self._lock:
            self.nodes.pop(node_id, None)
            self._bump()

    def _bump(self) -> None:
        self.revision += 1
        if self._path:
            self.save()

    # ---- queries --------------------------------------------------------
    def nodes_in_pool(self, cluster: str, pool: str) -> list[Node]:
        return [n for n in self.nodes.values()
                if n.cluster == cluster and n.pool == pool]

    def live_nodes_in_pool(self, cluster: str, pool: str) -> list[Node]:
        from .models import LIVE_STATES
        return [n for n in self.nodes_in_pool(cluster, pool)
                if n.state in LIVE_STATES]

    def all_nodes(self) -> Iterable[Node]:
        return list(self.nodes.values())

    # ---- persistence ----------------------------------------------------
    def save(self) -> None:
        if not self._path:
            return
        data = {
            "revision": self.revision,
            "clusters": {k: v.to_dict() for k, v in self.clusters.items()},
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
        }
        tmp = f"{self._path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        # Atomic replace, with retry: on Windows (esp. synced dirs like OneDrive/
        # Dropbox) the target can be transiently locked by the sync/AV process,
        # surfacing as PermissionError. Retry with backoff before giving up.
        last_err: Exception | None = None
        for attempt in range(10):
            try:
                os.replace(tmp, self._path)
                return
            except PermissionError as e:  # transient sharing violation
                last_err = e
                time.sleep(0.05 * (attempt + 1))
        # final fallback: best-effort direct write so we never crash the loop
        try:
            with open(self._path, "w") as f:
                json.dump(data, f, indent=2)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if last_err and not os.path.exists(self._path):
            raise last_err

    def load(self) -> None:
        with open(self._path) as f:
            data = json.load(f)
        self.revision = data.get("revision", 0)
        self.clusters = {}
        for name, c in data.get("clusters", {}).items():
            pools = {
                pk: NodePool(**pv) for pk, pv in c.get("pools", {}).items()
            }
            self.clusters[name] = Cluster(
                name=c["name"], pools=pools,
                state=ClusterState(c["state"]),
                desired_state=ClusterState(c["desired_state"]),
                created_at=c.get("created_at", 0.0),
            )
        self.nodes = {}
        for nid, n in data.get("nodes", {}).items():
            n = dict(n)
            n["state"] = NodeState(n["state"])
            self.nodes[nid] = Node(**n)
