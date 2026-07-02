"""Unit: domain models + the state store (persistence, queries)."""
import os
import tempfile
import unittest

from control_plane.models import Node, NodePool, Cluster, NodeState
from control_plane.store import Store


class TestModels(unittest.TestCase):
    def test_node_ids_unique(self):
        ids = {Node(pool="p", cluster="c", provider="aws", instance_type="t").id
               for _ in range(1000)}
        self.assertEqual(len(ids), 1000)

    def test_node_to_dict_serializes_enum(self):
        n = Node(pool="p", cluster="c", provider="aws", instance_type="t")
        self.assertEqual(n.to_dict()["state"], "REQUESTED")

    def test_pool_defaults(self):
        p = NodePool("p", "aws", "t", 3)
        self.assertEqual(p.max_unavailable, 1)
        self.assertEqual(p.max_provision, 100)


class TestStore(unittest.TestCase):
    def test_put_and_query_pool(self):
        s = Store()
        for _ in range(5):
            s.put_node(Node(pool="gpu", cluster="c", provider="aws", instance_type="t"))
        self.assertEqual(len(s.nodes_in_pool("c", "gpu")), 5)

    def test_revision_bumps_on_mutation(self):
        s = Store()
        r0 = s.revision
        s.put_node(Node(pool="p", cluster="c", provider="aws", instance_type="t"))
        self.assertEqual(s.revision, r0 + 1)

    def test_live_nodes_excludes_terminated(self):
        s = Store()
        a = Node(pool="p", cluster="c", provider="aws", instance_type="t")
        b = Node(pool="p", cluster="c", provider="aws", instance_type="t")
        b.state = NodeState.TERMINATED
        s.put_node(a)
        s.put_node(b)
        self.assertEqual(len(s.live_nodes_in_pool("c", "p")), 0)
        a.state = NodeState.HEALTHY
        s.put_node(a)
        self.assertEqual(len(s.live_nodes_in_pool("c", "p")), 1)

    def test_persistence_roundtrip(self):
        path = os.path.join(tempfile.mkdtemp(), "state.json")
        s = Store(path)
        c = Cluster(name="c")
        c.pools["p"] = NodePool("p", "gcp", "a3", 2)
        s.put_cluster(c)
        n = Node(pool="p", cluster="c", provider="gcp", instance_type="a3")
        n.state = NodeState.HEALTHY
        s.put_node(n)

        s2 = Store(path)  # reload from disk
        self.assertIn("c", s2.clusters)
        self.assertEqual(s2.clusters["c"].pools["p"].provider, "gcp")
        self.assertEqual(list(s2.nodes.values())[0].state, NodeState.HEALTHY)


if __name__ == "__main__":
    unittest.main()
