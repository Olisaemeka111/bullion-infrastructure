"""Integration: provisioning a cluster to its desired state."""
import unittest

from tests.helpers import (make_env, pool, multicloud_pools,
                           assert_system_invariants, assert_pool_at_desired)
from control_plane.models import NodeState, ClusterState


class TestProvisioning(unittest.TestCase):
    def test_single_pool_converges(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 5, max_provision=5)])
        env.converge()
        self.assertEqual(env.healthy(), 5)
        self.assertEqual(env.store.clusters["c"].state, ClusterState.ACTIVE)
        assert_system_invariants(self, env)

    def test_multicloud_and_onprem_converges(self):
        env = make_env()
        env.apply("c", multicloud_pools(per_provider=50, baremetal=20))
        env.converge()
        self.assertEqual(env.healthy(), 50 * 3 + 20)
        for p in ("aws", "gcp", "azure", "metal"):
            assert_pool_at_desired(self, env, "c", p)
        assert_system_invariants(self, env)

    def test_every_healthy_node_passed_security_gate(self):
        env = make_env()
        env.apply("c", [pool("p", "gcp", 10, max_provision=10)])
        env.converge()
        for n in env.nodes(NodeState.HEALTHY):
            self.assertTrue(n.security_passed and n.attested)

    def test_reconcile_is_idempotent_after_convergence(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 4, max_provision=4)])
        env.converge()
        self.assertEqual(env.rec.tick()["actions"], [])

    def test_scale_up_then_down(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 3, max_unavailable=3, max_provision=3)])
        env.converge()
        self.assertEqual(env.healthy(), 3)
        env.api.scale_pool("c", "p", 6)
        env.converge()
        self.assertEqual(env.healthy(), 6)
        env.api.scale_pool("c", "p", 2)
        env.converge()
        self.assertEqual(env.healthy(), 2)
        assert_system_invariants(self, env)


if __name__ == "__main__":
    unittest.main()
