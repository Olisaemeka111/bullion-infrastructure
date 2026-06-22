"""Integration: failure detection + self-heal within safety budgets."""
import time
import unittest

from tests.helpers import make_env, pool, assert_system_invariants
from control_plane.models import NodeState


class TestSelfHealing(unittest.TestCase):
    def test_agent_reported_failure_replaced(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 3, max_unavailable=3, max_provision=3)])
        env.converge()
        victim = env.nodes(NodeState.HEALTHY)[0]
        vid = victim.id
        env.api.report_health(vid, "failed", time.time())
        env.converge()
        self.assertIsNone(env.store.nodes.get(vid))   # replaced + GC'd
        self.assertEqual(env.healthy(), 3)            # capacity restored
        assert_system_invariants(self, env)

    def test_heartbeat_timeout_detected(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 2, max_unavailable=2, max_provision=2)])
        env.converge()
        n = env.nodes(NodeState.HEALTHY)[0]
        env.api.report_health(n.id, "healthy", time.time() - 10_000)  # stale
        env.rec.tick()
        refreshed = env.store.nodes.get(n.id)
        if refreshed is not None:
            self.assertNotEqual(refreshed.state, NodeState.HEALTHY)

    def test_self_heal_recovers_full_capacity(self):
        env = make_env()
        env.apply("c", [pool("p", "gcp", 10, max_unavailable=10, max_provision=10)])
        env.converge()
        for n in env.nodes(NodeState.HEALTHY)[:4]:
            env.api.report_health(n.id, "failed", time.time())
        env.converge()
        self.assertEqual(env.healthy(), 10)

    def test_metrics_record_failures_and_heals(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 5, max_unavailable=5, max_provision=5)])
        env.converge()
        for n in env.nodes(NodeState.HEALTHY)[:3]:
            env.api.report_health(n.id, "failed", time.time())
        env.converge()
        snap = env.telemetry.registry.snapshot()
        failed = sum(v for (n, _), v in snap.items()
                     if n == "clusterinfra_nodes_failed_total")
        heals = sum(v for (n, _), v in snap.items()
                    if n == "clusterinfra_self_heal_total")
        self.assertEqual(failed, 3)
        self.assertEqual(heals, 3)


if __name__ == "__main__":
    unittest.main()
