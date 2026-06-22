"""Unit: metrics registry + telemetry collector (no control loop)."""
import unittest

from observability.metrics import MetricsRegistry
from observability.telemetry import Telemetry
from control_plane.store import Store
from control_plane.models import Cluster, NodePool, Node, NodeState


class TestMetricsRegistry(unittest.TestCase):
    def test_counter_accumulates_per_label(self):
        r = MetricsRegistry()
        c = r.counter("things_total")
        c.inc(provider="aws")
        c.inc(provider="aws")
        c.inc(provider="gcp")
        snap = r.snapshot()
        self.assertEqual(snap[("things_total", (("provider", "aws"),))], 2)
        self.assertEqual(snap[("things_total", (("provider", "gcp"),))], 1)

    def test_gauge_set_and_clear(self):
        r = MetricsRegistry()
        g = r.gauge("g")
        g.set(5, pool="a")
        self.assertEqual(r.snapshot()[("g", (("pool", "a"),))], 5)
        g.clear()
        self.assertEqual(r.snapshot(), {})

    def test_prometheus_exposition_format(self):
        r = MetricsRegistry()
        r.counter("reqs_total", "total reqs").inc(2, code="200")
        text = r.render_prometheus()
        self.assertIn("# TYPE reqs_total counter", text)
        self.assertIn('reqs_total{code="200"} 2', text)


class TestTelemetryCollect(unittest.TestCase):
    def test_collect_derives_pool_gauges(self):
        store = Store()
        c = Cluster(name="c")
        c.pools["p"] = NodePool("p", "aws", "t", desired_count=3)
        store.put_cluster(c)
        for _ in range(2):
            n = Node(pool="p", cluster="c", provider="aws", instance_type="t")
            n.state = NodeState.HEALTHY
            store.put_node(n)

        tel = Telemetry()
        tel.collect(store)
        snap = tel.registry.snapshot()
        healthy = snap[("clusterinfra_pool_healthy_nodes",
                        (("cluster", "c"), ("pool", "p"), ("provider", "aws")))]
        avail = snap[("clusterinfra_pool_availability_ratio",
                      (("cluster", "c"), ("pool", "p"), ("provider", "aws")))]
        self.assertEqual(healthy, 2)
        self.assertAlmostEqual(avail, 2 / 3, places=3)


if __name__ == "__main__":
    unittest.main()
