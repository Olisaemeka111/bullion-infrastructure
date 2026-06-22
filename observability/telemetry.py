"""Named metrics for the cluster control plane + a collector that derives the
gauges from the store. The reconciler holds a Telemetry instance and increments
counters as it acts; `collect()` is called each tick to refresh fleet gauges.
"""
from __future__ import annotations

from .metrics import MetricsRegistry
from control_plane.models import NodeState


class Telemetry:
    def __init__(self, registry: MetricsRegistry | None = None):
        self.registry = registry or MetricsRegistry()
        r = self.registry
        # counters (monotonic events)
        self.reconcile_ticks = r.counter(
            "clusterinfra_reconcile_ticks_total", "Reconcile ticks executed")
        self.actions = r.counter(
            "clusterinfra_reconcile_actions_total", "Reconcile actions by type")
        self.nodes_created = r.counter(
            "clusterinfra_nodes_created_total", "Nodes created by provider")
        self.nodes_failed = r.counter(
            "clusterinfra_nodes_failed_total", "Nodes marked FAILED by reason")
        self.self_heals = r.counter(
            "clusterinfra_self_heal_total", "Self-heal replacements started")
        self.security_rejections = r.counter(
            "clusterinfra_security_gate_rejections_total",
            "Nodes rejected by the secure-by-default admission gate")
        self.nodes_terminated = r.counter(
            "clusterinfra_nodes_terminated_total", "Nodes fully decommissioned")
        # gauges (point-in-time fleet state)
        self.nodes_by_state = r.gauge(
            "clusterinfra_nodes", "Node count by cluster/pool/provider/state")
        self.pool_desired = r.gauge(
            "clusterinfra_pool_desired_nodes", "Desired node count per pool")
        self.pool_healthy = r.gauge(
            "clusterinfra_pool_healthy_nodes", "Healthy node count per pool")
        self.pool_availability = r.gauge(
            "clusterinfra_pool_availability_ratio", "healthy/desired per pool")
        self.cluster_state = r.gauge(
            "clusterinfra_cluster_state_info", "Cluster state (1=current)")

    # ---- gauge collection from store ----------------------------------
    def collect(self, store) -> None:
        self.nodes_by_state.clear()
        self.pool_desired.clear()
        self.pool_healthy.clear()
        self.pool_availability.clear()
        self.cluster_state.clear()

        for cname, cluster in store.clusters.items():
            self.cluster_state.set(1, cluster=cname, state=cluster.state.value)
            for pname, pool in cluster.pools.items():
                nodes = store.nodes_in_pool(cname, pname)
                counts: dict[str, int] = {}
                for n in nodes:
                    counts[n.state.value] = counts.get(n.state.value, 0) + 1
                for state, c in counts.items():
                    self.nodes_by_state.set(
                        c, cluster=cname, pool=pname,
                        provider=pool.provider, state=state)
                healthy = counts.get(NodeState.HEALTHY.value, 0)
                self.pool_desired.set(pool.desired_count, cluster=cname,
                                      pool=pname, provider=pool.provider)
                self.pool_healthy.set(healthy, cluster=cname, pool=pname,
                                      provider=pool.provider)
                ratio = healthy / pool.desired_count if pool.desired_count else 1.0
                self.pool_availability.set(round(ratio, 4), cluster=cname,
                                           pool=pname, provider=pool.provider)
