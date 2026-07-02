"""Integration: durable workflow orchestration (Temporal-style)."""
import unittest

from tests.helpers import make_env, pool, assert_homogeneous
from control_plane.models import NodeState
from workflows.orchestration import (cluster_bringup_workflow,
                                      cluster_decommission_workflow,
                                      activity_verify_homogeneity)


class TestOrchestration(unittest.TestCase):
    def test_bringup_workflow_succeeds_and_verifies(self):
        env = make_env()
        env.apply("c", [
            pool("aws", "aws", 30, max_unavailable=15, max_provision=30),
            pool("metal", "baremetal", 10, max_unavailable=10, max_provision=30),
        ])
        wf = cluster_bringup_workflow(env.api, env.rec, env.store, "c")
        self.assertTrue(wf.ok, [r.__dict__ for r in wf.results])
        self.assertEqual(env.healthy(), 40)
        assert_homogeneous(self, env, "c", "aws")

    def test_homogeneity_activity_detects_divergence(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 3, max_unavailable=3, max_provision=3)])
        env.converge()
        # corrupt one node's config hash to simulate drift
        n = env.nodes(NodeState.HEALTHY)[0]
        n.config_hash = "DRIFTED"
        env.store.put_node(n)
        result = activity_verify_homogeneity(env.store, "c")
        self.assertFalse(result.ok)

    def test_decommission_workflow_empties_cluster(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 5, max_unavailable=5, max_provision=5)])
        env.converge()
        wf = cluster_decommission_workflow(env.api, env.rec, "c")
        self.assertTrue(wf.ok)
        self.assertEqual(len(list(env.store.all_nodes())), 0)


if __name__ == "__main__":
    unittest.main()
