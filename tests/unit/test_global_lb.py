"""Unit tests: active-active global traffic director (networking/global_lb.py)."""
import unittest

from control_plane.models import Node, NodeState
from control_plane.store import Store
from networking.global_lb import GlobalTrafficDirector

CLUSTER = "fleet-mini"


def _seed(store, per_cloud):
    """Create `n` HEALTHY nodes per provider in CLUSTER."""
    for provider, n in per_cloud.items():
        for _ in range(n):
            node = Node(pool=f"{provider}-nodes", cluster=CLUSTER,
                        provider=provider, instance_type="medium",
                        state=NodeState.HEALTHY)
            store.put_node(node)


class TestGlobalTrafficDirector(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.gtd = GlobalTrafficDirector(self.store, CLUSTER)

    def test_balances_across_all_clouds_active_active(self):
        _seed(self.store, {"aws": 2, "gcp": 2, "azure": 2})
        w = self.gtd.weights()
        self.assertEqual(set(w), {"aws", "gcp", "azure"})
        for cloud in w:
            self.assertAlmostEqual(w[cloud], 1 / 3, places=2)  # all serving, equal

    def test_weights_track_capacity(self):
        _seed(self.store, {"aws": 4, "gcp": 2, "azure": 2})
        w = self.gtd.weights()
        self.assertAlmostEqual(w["aws"], 0.5, places=2)  # twice the capacity
        self.assertAlmostEqual(w["gcp"], 0.25, places=2)

    def test_allocation_sums_to_requests_exactly(self):
        _seed(self.store, {"aws": 2, "gcp": 2, "azure": 2})
        d = self.gtd.distribute(10000)
        self.assertEqual(sum(d.allocation.values()), 10000)

    def test_outage_redistributes_to_survivors(self):
        _seed(self.store, {"aws": 2, "gcp": 2, "azure": 2})
        d = self.gtd.distribute(9000, down={"aws"})
        self.assertEqual(d.allocation.get("aws", 0), 0)        # AWS sheds all traffic
        self.assertNotIn("aws", d.serving_clouds)
        self.assertIn("aws", d.drained_clouds)
        self.assertEqual(sum(d.allocation.values()), 9000)     # nothing dropped
        self.assertAlmostEqual(d.weights["gcp"], 0.5, places=2)  # split across the 2 left

    def test_recovery_rebalances(self):
        _seed(self.store, {"aws": 2, "gcp": 2, "azure": 2})
        self.gtd.distribute(100, down={"aws"})   # during outage
        w = self.gtd.weights()                    # after recovery (no down set)
        self.assertAlmostEqual(w["aws"], 1 / 3, places=2)

    def test_unhealthy_nodes_excluded(self):
        _seed(self.store, {"aws": 2, "gcp": 2})
        # add a non-healthy node; it must not count toward serving capacity
        self.store.put_node(Node(pool="aws-nodes", cluster=CLUSTER, provider="aws",
                                 instance_type="medium", state=NodeState.FAILED))
        self.assertEqual(self.gtd.capacity_by_cloud(), {"aws": 2, "gcp": 2})


if __name__ == "__main__":
    unittest.main()
