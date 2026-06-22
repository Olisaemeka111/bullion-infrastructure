"""Chaos: inject provider/provisioning failures and correlated outages, then
assert the system still converges and never violates safety invariants."""
import time
import unittest

from tests.helpers import make_env, pool, multicloud_pools, assert_system_invariants
from control_plane.models import NodeState


class TestProvisioningFlakiness(unittest.TestCase):
    def test_converges_despite_provider_create_failures(self):
        # 30% of instance creates fail; the reconciler must retry/replace and
        # still reach desired capacity.
        env = make_env(failure_rate=0.30)
        env.apply("c", [pool("p", "aws", 20, max_unavailable=20, max_provision=20)])
        env.converge(max_ticks=500)
        self.assertEqual(env.healthy(), 20)
        assert_system_invariants(self, env)

    def test_high_failure_rate_still_eventually_converges(self):
        env = make_env(failure_rate=0.6)
        env.apply("c", [pool("p", "gcp", 10, max_unavailable=10, max_provision=10)])
        env.converge(max_ticks=1000)
        self.assertEqual(env.healthy(), 10)


class TestCorrelatedOutage(unittest.TestCase):
    def test_budget_caps_blast_radius_under_mass_failure(self):
        # fail an entire pool at once; only max_unavailable may be destroyed
        # concurrently, so we never stampede-delete the pool.
        env = make_env()
        env.apply("c", [pool("p", "aws", 12, max_unavailable=2, max_provision=12)])
        env.converge()
        for n in env.nodes(NodeState.HEALTHY):
            env.api.report_health(n.id, "failed", time.time())
        # step a few ticks and assert budget invariant holds throughout recovery
        for _ in range(60):
            env.rec.tick()
            assert_system_invariants(self, env)
        self.assertEqual(env.healthy(), 12)  # fully recovered

    def test_one_provider_outage_does_not_affect_others(self):
        env = make_env()
        env.apply("c", multicloud_pools(per_provider=20, baremetal=10,
                                        max_unavailable=20, max_provision=40))
        env.converge()
        # wipe out gcp only
        for n in env.nodes(NodeState.HEALTHY):
            if n.provider == "gcp":
                env.api.report_health(n.id, "failed", time.time())
        env.converge()
        # all pools back to desired; other providers never dipped
        self.assertEqual(env.healthy(), 20 * 3 + 10)
        assert_system_invariants(self, env)


if __name__ == "__main__":
    unittest.main()
