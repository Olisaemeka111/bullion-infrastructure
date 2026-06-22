"""Thin command surface over the store + reconciler.

This is the operator-facing API (in prod: gRPC/HTTP behind mTLS + RBAC). It only
mutates *desired* state; the reconciler is solely responsible for driving
observed state toward it.
"""
from __future__ import annotations

from .models import Cluster, NodePool, NodeState, ClusterState
from .store import Store
from .state_machine import transition
from workflows import update as update_wf


class ControlPlaneAPI:
    def __init__(self, store: Store):
        self.store = store

    def apply_cluster(self, name: str, pools: list[NodePool]) -> Cluster:
        """Declare (or update) a cluster spec."""
        cluster = self.store.clusters.get(name) or Cluster(name=name)
        for p in pools:
            cluster.pools[p.name] = p
        cluster.desired_state = ClusterState.ACTIVE
        self.store.put_cluster(cluster)
        return cluster

    def scale_pool(self, cluster: str, pool: str, desired: int) -> None:
        c = self.store.clusters[cluster]
        c.pools[pool].desired_count = desired
        self.store.put_cluster(c)

    def rolling_update(self, cluster: str, pool: str, new_image: str) -> int:
        """Declare a new desired golden image for a pool. The reconciler rolls the
        pool to it. Returns the number of nodes still on the old image."""
        return update_wf.plan(self.store, cluster, pool, new_image)

    def decommission_cluster(self, cluster: str) -> None:
        c = self.store.clusters[cluster]
        c.desired_state = ClusterState.DECOMMISSIONED
        self.store.put_cluster(c)

    def report_health(self, node_id: str, status: str, ts: float) -> None:
        """Ingest an agent health report (the self-healing input signal)."""
        node = self.store.nodes.get(node_id)
        if not node:
            return
        node.health = status
        node.last_heartbeat = ts
        self.store.put_node(node)

    def force_decommission_node(self, node_id: str, approved_by: str) -> None:
        """Emergency teardown that bypasses the drain guard. Requires an approver
        so every safe-by-default bypass is auditable."""
        node = self.store.nodes[node_id]
        transition(node, NodeState.DECOMMISSIONING,
                   "emergency teardown", force=True, approved_by=approved_by)
        self.store.put_node(node)

    def status(self) -> dict:
        out = {}
        for name, c in self.store.clusters.items():
            pools = {}
            for pname, p in c.pools.items():
                nodes = self.store.nodes_in_pool(name, pname)
                by_state: dict[str, int] = {}
                for n in nodes:
                    by_state[n.state.value] = by_state.get(n.state.value, 0) + 1
                pools[pname] = {
                    "provider": p.provider,
                    "desired": p.desired_count,
                    "image": p.image_digest,
                    "by_state": by_state,
                }
            out[name] = {"state": c.state.value,
                         "desired": c.desired_state.value, "pools": pools}
        return out
