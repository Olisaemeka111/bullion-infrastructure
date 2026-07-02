"""Integration: decommissioning (whole cluster + forced node teardown)."""
import unittest

from tests.helpers import make_env, pool, assert_system_invariants
from control_plane.models import NodeState, ClusterState


class TestDecommission(unittest.TestCase):
    def test_cluster_decommission_removes_everything(self):
        env = make_env()
        env.apply("c", [
            pool("a", "aws", 4, max_unavailable=4, max_provision=4),
            pool("b", "gcp", 4, max_unavailable=4, max_provision=4),
        ])
        env.converge()
        env.api.decommission_cluster("c")
        env.converge()
        self.assertEqual(len(list(env.store.all_nodes())), 0)
        self.assertEqual(env.store.clusters["c"].state, ClusterState.DECOMMISSIONED)

    def test_nodes_route_through_draining(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 3, max_unavailable=1, max_provision=3)])
        env.converge()
        env.api.decommission_cluster("c")
        # first decommission tick must DRAIN (not jump straight to terminated)
        env.rec.tick()
        states = {n.state for n in env.store.all_nodes()}
        self.assertNotIn(NodeState.TERMINATED, states)
        assert_system_invariants(self, env)
        env.converge()
        self.assertEqual(len(list(env.store.all_nodes())), 0)

    def test_decommission_reaches_noaction_steady_state(self):
        # regression: a decommissioned cluster must be a reconcile no-op, not
        # flip-flop DRAINING<->DECOMMISSIONED forever.
        env = make_env()
        env.apply("c", [pool("p", "aws", 3, max_unavailable=3, max_provision=3)])
        env.converge()
        env.api.decommission_cluster("c")
        ticks = env.converge(max_ticks=100)
        self.assertLess(ticks, 100, "decommission did not converge")
        self.assertEqual(env.rec.tick()["actions"], [])  # truly idle

    def test_force_decommission_requires_approver(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 1, max_unavailable=1, max_provision=1)])
        env.converge()
        n = env.nodes(NodeState.HEALTHY)[0]
        env.api.force_decommission_node(n.id, approved_by="alice")
        self.assertEqual(env.store.nodes[n.id].state, NodeState.DECOMMISSIONING)
        self.assertIn("FORCED by alice", env.store.nodes[n.id].reason)


if __name__ == "__main__":
    unittest.main()
