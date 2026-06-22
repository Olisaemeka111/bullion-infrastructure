"""The reconciler: a level-triggered control loop.

Each `tick()` derives the minimal set of actions from (desired, observed) and
applies them. It is the core of agent-driven automation:

- IDEMPOTENT: re-running a tick from the same state is a no-op.
- RESTARTABLE: all state is in the Store, so a crashed control plane resumes.
- SAFE-BY-DEFAULT: destructive actions (drain/replace) respect per-pool budgets
  and a global rate limit, so a correlated failure can never stampede an entire
  cluster into deletion.
- SELF-HEALING: nodes the agents report as FAILED (or that miss heartbeats) are
  automatically drained and replaced within budget.
"""
from __future__ import annotations

import time

from .models import (Cluster, Node, NodePool, NodeState, ClusterState,
                     LIVE_STATES)
from .store import Store
from .state_machine import transition
from providers.registry import ProviderRegistry
from workflows import provision, drain, decommission
from observability.telemetry import Telemetry

HEARTBEAT_TIMEOUT = 30.0  # seconds before a silent node is presumed FAILED


class Reconciler:
    def __init__(self, store: Store, registry: ProviderRegistry,
                 global_max_replacements: int = 50,
                 telemetry: Telemetry | None = None):
        self.store = store
        self.registry = registry
        self.global_max_replacements = global_max_replacements
        self.telemetry = telemetry or Telemetry()

    # ---- main entry -----------------------------------------------------
    def tick(self, now: float | None = None) -> dict:
        now = now or time.time()
        actions: list[str] = []
        self._detect_failures(now, actions)
        for cluster in list(self.store.clusters.values()):
            self._reconcile_cluster(cluster, actions)
        self._gc_terminated(actions)
        # metrics
        self.telemetry.reconcile_ticks.inc()
        for a in actions:
            self.telemetry.actions.inc(type=a.split(" ", 1)[0])
        self.telemetry.collect(self.store)
        return {"revision": self.store.revision, "actions": actions}

    # ---- failure detection (self-healing trigger) ----------------------
    def _detect_failures(self, now: float, actions: list[str]) -> None:
        for node in self.store.all_nodes():
            if node.state == NodeState.HEALTHY:
                if node.last_heartbeat and now - node.last_heartbeat > HEARTBEAT_TIMEOUT:
                    transition(node, NodeState.FAILED, "heartbeat timeout")
                    self.store.put_node(node)
                    actions.append(f"detect-failed {node.id}")
                    self.telemetry.nodes_failed.inc(reason="heartbeat_timeout",
                                                    provider=node.provider)
                elif node.health == "failed":
                    transition(node, NodeState.FAILED, "agent reported failure")
                    self.store.put_node(node)
                    actions.append(f"detect-failed {node.id}")
                    self.telemetry.nodes_failed.inc(reason="agent_reported",
                                                    provider=node.provider)

    # ---- per-cluster reconciliation ------------------------------------
    def _reconcile_cluster(self, cluster: Cluster, actions: list[str]) -> None:
        if cluster.state == ClusterState.PLANNED:
            cluster.state = ClusterState.PROVISIONING
            self.store.put_cluster(cluster)

        # Whole-cluster teardown requested.
        if cluster.desired_state == ClusterState.DECOMMISSIONED:
            self._drain_cluster(cluster, actions)
            return

        replacements_used = 0
        for pool in cluster.pools.values():
            replacements_used += self._reconcile_pool(
                cluster, pool, actions, budget_left=self.global_max_replacements - replacements_used)

        # cluster becomes ACTIVE once every pool is at desired healthy count
        if all(self._pool_satisfied(cluster.name, p) for p in cluster.pools.values()):
            if cluster.state != ClusterState.ACTIVE:
                cluster.state = ClusterState.ACTIVE
                self.store.put_cluster(cluster)

    def _pool_satisfied(self, cluster_name: str, pool: NodePool) -> bool:
        healthy = [n for n in self.store.nodes_in_pool(cluster_name, pool.name)
                   if n.state == NodeState.HEALTHY]
        return len(healthy) >= pool.desired_count

    def _reconcile_pool(self, cluster: Cluster, pool: NodePool,
                       actions: list[str], budget_left: int) -> int:
        provider = self.registry.get(pool.provider)
        used = 0

        # 1. advance every in-flight node one stage (provision / drain / decommission)
        for node in self.store.nodes_in_pool(cluster.name, pool.name):
            before = node.state
            self._advance(node, pool, provider)
            if node.state != before:
                actions.append(f"advance {node.id} {before.value}->{node.state.value}")
                self.store.put_node(node)
                if node.state == NodeState.FAILED and node.reason.startswith("security gate"):
                    self.telemetry.security_rejections.inc(provider=pool.provider)
                    self.telemetry.nodes_failed.inc(reason="security_gate",
                                                    provider=pool.provider)

        # 2. self-heal: FAILED nodes get drained+replaced within budget
        failed = [n for n in self.store.nodes_in_pool(cluster.name, pool.name)
                  if n.state == NodeState.FAILED]
        in_flight_destructive = sum(
            1 for n in self.store.nodes_in_pool(cluster.name, pool.name)
            if n.state in (NodeState.DRAINING, NodeState.DECOMMISSIONING))
        repl_budget = min(budget_left, max(0, pool.max_unavailable - in_flight_destructive))
        for node in failed[:repl_budget]:
            drain.start(node, reason="self-heal: replacing failed node")
            self.store.put_node(node)
            actions.append(f"self-heal {node.id} -> DRAINING")
            self.telemetry.self_heals.inc(provider=pool.provider)
            used += 1

        # 2b. rolling update: drain HEALTHY nodes whose image != the pool's desired
        # golden image, within the SAME max_unavailable destructive budget. This is
        # what makes rolling updates level-triggered — the operator sets the desired
        # image once (pool.image_digest) and the reconciler rolls the whole pool to
        # it across ticks; scale-up (below) refills each gap with the new image.
        in_flight_destructive = sum(
            1 for n in self.store.nodes_in_pool(cluster.name, pool.name)
            if n.state in (NodeState.DRAINING, NodeState.DECOMMISSIONING))
        roll_budget = max(0, pool.max_unavailable - in_flight_destructive)
        stale = [n for n in self.store.nodes_in_pool(cluster.name, pool.name)
                 if n.state == NodeState.HEALTHY
                 and n.image_digest != pool.image_digest]
        for node in stale[:roll_budget]:
            drain.start(node, reason=f"rolling update -> {pool.image_digest}")
            self.store.put_node(node)
            actions.append(f"rolling-update {node.id} -> DRAINING")

        # 3. scale up: create nodes if below desired count
        live = self.store.live_nodes_in_pool(cluster.name, pool.name)
        # only count nodes that are not on their way out
        contributing = [n for n in live if n.state not in (
            NodeState.DRAINING, NodeState.DECOMMISSIONING, NodeState.FAILED)]
        deficit = pool.desired_count - len(contributing)
        # creation is non-destructive: gated by provisioning concurrency, NOT the
        # destructive replacement budget.
        create_budget = min(deficit, pool.max_provision)
        for _ in range(max(0, create_budget)):
            node = Node(pool=pool.name, cluster=cluster.name, provider=pool.provider,
                        instance_type=pool.instance_type)
            self.store.put_node(node)
            actions.append(f"create {node.id} in {cluster.name}/{pool.name}")
            self.telemetry.nodes_created.inc(provider=pool.provider)
            if cluster.state == ClusterState.ACTIVE:
                cluster.state = ClusterState.SCALING
                self.store.put_cluster(cluster)

        # 4. scale down: if above desired, drain the excess (destructive -> budgeted)
        if deficit < 0:
            excess = -deficit
            in_flight = sum(1 for n in self.store.nodes_in_pool(cluster.name, pool.name)
                            if n.state in (NodeState.DRAINING, NodeState.DECOMMISSIONING))
            down_budget = max(0, min(excess, pool.max_unavailable - in_flight))
            healthy = [n for n in self.store.nodes_in_pool(cluster.name, pool.name)
                       if n.state == NodeState.HEALTHY]
            for node in healthy[:down_budget]:
                drain.start(node, reason="scale-down")
                self.store.put_node(node)
                actions.append(f"scale-down {node.id} -> DRAINING")

        return used

    def _advance(self, node: Node, pool: NodePool, provider) -> None:
        s = node.state
        if s in (NodeState.REQUESTED, NodeState.PROVISIONING,
                 NodeState.BOOTSTRAPPING, NodeState.REGISTERING):
            provision.step(node, pool, provider)
        elif s == NodeState.DRAINING:
            drain.step(node, pool, provider)
        elif s == NodeState.DECOMMISSIONING:
            decommission.step(node, pool, provider)
        # HEALTHY / UPDATING / TERMINATED need no automatic advance here

    # ---- cluster teardown ----------------------------------------------
    def _drain_cluster(self, cluster: Cluster, actions: list[str]) -> None:
        if cluster.state == ClusterState.DECOMMISSIONED:
            return  # terminal: nothing left to do (keeps reconcile a no-op)
        if cluster.state != ClusterState.DRAINING:
            cluster.state = ClusterState.DRAINING
            self.store.put_cluster(cluster)
        any_live = False
        for pool in cluster.pools.values():
            provider = self.registry.get(pool.provider)
            for node in self.store.nodes_in_pool(cluster.name, pool.name):
                if node.state in LIVE_STATES:
                    any_live = True
                    before = node.state
                    if node.state in (NodeState.HEALTHY, NodeState.FAILED,
                                      NodeState.UPDATING):
                        drain.start(node, "cluster decommission")
                    self._advance(node, pool, provider)
                    if node.state != before:
                        actions.append(
                            f"advance {node.id} {before.value}->{node.state.value}")
                    self.store.put_node(node)
        if not any_live:
            cluster.state = ClusterState.DECOMMISSIONED
            self.store.put_cluster(cluster)
            actions.append(f"cluster {cluster.name} DECOMMISSIONED")

    # ---- garbage collection --------------------------------------------
    def _gc_terminated(self, actions: list[str]) -> None:
        for node in list(self.store.all_nodes()):
            if node.state == NodeState.TERMINATED:
                self.store.remove_node(node.id)
                actions.append(f"gc {node.id}")
                self.telemetry.nodes_terminated.inc(provider=node.provider)

    # ---- convergence helper for demos/tests ----------------------------
    def run_until_converged(self, max_ticks: int = 100,
                            now_fn=None) -> int:
        """Tick until no actions are produced (or max_ticks). Returns tick count."""
        for i in range(1, max_ticks + 1):
            now = now_fn() if now_fn else time.time()
            result = self.tick(now)
            if not result["actions"]:
                return i
        return max_ticks
