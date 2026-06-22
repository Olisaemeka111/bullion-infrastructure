"""Shared test fixtures, builders, and invariant assertions.

Centralizing these keeps individual tests short and makes the *system invariants*
explicit and reusable: any integration or chaos test can call
`assert_system_invariants()` to assert the safety properties the design promises,
no matter what sequence of operations it just ran.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from control_plane.models import NodePool, NodeState, ClusterState, LIVE_STATES
from control_plane.store import Store
from control_plane.api import ControlPlaneAPI
from control_plane.reconciler import Reconciler
from providers.registry import ProviderRegistry
from observability.telemetry import Telemetry


# ---- environment fixture -------------------------------------------------
class Env:
    """A fully-wired, in-memory control plane for tests."""

    def __init__(self, failure_rate: float = 0.0,
                 global_max_replacements: int = 50):
        self.store = Store()
        self.telemetry = Telemetry()
        self.registry = ProviderRegistry(failure_rate=failure_rate)
        self.rec = Reconciler(self.store, self.registry,
                              global_max_replacements=global_max_replacements,
                              telemetry=self.telemetry)
        self.api = ControlPlaneAPI(self.store)

    # convenience pass-throughs
    def apply(self, cluster: str, pools: list[NodePool]):
        return self.api.apply_cluster(cluster, pools)

    def converge(self, max_ticks: int = 500) -> int:
        return self.rec.run_until_converged(max_ticks=max_ticks)

    def tick(self, n: int = 1):
        for _ in range(n):
            self.rec.tick()

    # queries
    def nodes(self, state: NodeState | None = None):
        ns = list(self.store.all_nodes())
        return [x for x in ns if state is None or x.state == state]

    def count(self, state: NodeState) -> int:
        return len(self.nodes(state))

    def healthy(self) -> int:
        return self.count(NodeState.HEALTHY)


def make_env(**kw) -> Env:
    return Env(**kw)


def pool(name: str, provider: str, count: int, *, instance_type: str = "t-test",
         max_unavailable: int = 1, max_provision: int = 100,
         image: str = "sha256:GOLD-v1") -> NodePool:
    return NodePool(name=name, provider=provider, instance_type=instance_type,
                    desired_count=count, max_unavailable=max_unavailable,
                    max_provision=max_provision, image_digest=image)


def multicloud_pools(per_provider: int = 50, baremetal: int = 20,
                     max_unavailable: int = 10, max_provision: int = 100):
    return [
        pool("aws", "aws", per_provider, max_unavailable=max_unavailable, max_provision=max_provision),
        pool("gcp", "gcp", per_provider, max_unavailable=max_unavailable, max_provision=max_provision),
        pool("azure", "azure", per_provider, max_unavailable=max_unavailable, max_provision=max_provision),
        pool("metal", "baremetal", baremetal, max_unavailable=max_unavailable, max_provision=max_provision),
    ]


# ---- invariant assertions (the design's safety properties) ---------------
def assert_system_invariants(tc, env: Env) -> None:
    """Assert properties that must hold after ANY sequence of operations."""
    store = env.store

    for n in store.all_nodes():
        # 1. no node is left in a non-existent/terminal-but-present state
        tc.assertNotEqual(n.state, NodeState.TERMINATED,
                          f"{n.id} TERMINATED but not garbage-collected")
        # 2. any HEALTHY node passed the secure-by-default gate + attested + homogeneous signal
        if n.state == NodeState.HEALTHY:
            tc.assertTrue(n.security_passed, f"{n.id} HEALTHY without security gate")
            tc.assertTrue(n.attested, f"{n.id} HEALTHY without attestation")
            tc.assertIsNotNone(n.config_hash, f"{n.id} HEALTHY without config hash")
            tc.assertIsNotNone(n.instance_id, f"{n.id} HEALTHY without an instance")

    # 3. per-pool destructive concurrency never exceeds max_unavailable.
    #    Exception: a cluster being decommissioned intentionally drains everything
    #    at once - the budget protects *serving* clusters, not teardown.
    for cname, cluster in store.clusters.items():
        if cluster.desired_state == ClusterState.DECOMMISSIONED:
            continue
        for pname, p in cluster.pools.items():
            destructive = [n for n in store.nodes_in_pool(cname, pname)
                           if n.state in (NodeState.DRAINING, NodeState.DECOMMISSIONING)]
            tc.assertLessEqual(
                len(destructive), p.max_unavailable,
                f"{cname}/{pname}: {len(destructive)} destructive > budget {p.max_unavailable}")


def assert_pool_at_desired(tc, env: Env, cluster: str, pool_name: str) -> None:
    p = env.store.clusters[cluster].pools[pool_name]
    healthy = [n for n in env.store.nodes_in_pool(cluster, pool_name)
               if n.state == NodeState.HEALTHY]
    tc.assertEqual(len(healthy), p.desired_count,
                   f"{cluster}/{pool_name}: {len(healthy)} healthy != desired {p.desired_count}")


def assert_homogeneous(tc, env: Env, cluster: str, pool_name: str) -> None:
    healthy = [n for n in env.store.nodes_in_pool(cluster, pool_name)
               if n.state == NodeState.HEALTHY]
    hashes = {n.config_hash for n in healthy}
    images = {n.image_digest for n in healthy}
    tc.assertLessEqual(len(hashes), 1, f"{pool_name} config hashes diverged: {hashes}")
    tc.assertLessEqual(len(images), 1, f"{pool_name} images diverged: {images}")
