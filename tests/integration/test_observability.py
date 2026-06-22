"""Integration: metrics emitted by the live control loop + dashboard rendering."""
import time
import unittest

from tests.helpers import make_env, multicloud_pools
from control_plane.models import NodeState
from observability.dashboard import DashboardData, render_html


class TestObservabilityIntegration(unittest.TestCase):
    def test_prometheus_exposition_reflects_fleet(self):
        env = make_env()
        env.apply("c", multicloud_pools(per_provider=20, baremetal=10))
        env.converge()
        text = env.telemetry.registry.render_prometheus()
        self.assertIn("clusterinfra_pool_healthy_nodes", text)
        self.assertIn('provider="aws"', text)
        self.assertIn("# TYPE clusterinfra_reconcile_ticks_total counter", text)

    def test_dashboard_html_renders_from_run(self):
        env = make_env()
        env.apply("c", multicloud_pools(per_provider=15, baremetal=5))
        dash = DashboardData()
        for _ in range(15):
            env.rec.tick()
            dash.capture(len(dash.ticks), env.telemetry, env.store)
        dash.event("converged")
        html = render_html(dash, env.telemetry.registry.render_prometheus())
        self.assertIn("<!doctype html>", html)
        self.assertIn("Fleet Lifecycle", html)
        self.assertIn("nodes_by_state", html)  # data payload embedded

    def test_security_rejections_counter_zero_on_clean_fleet(self):
        env = make_env()
        env.apply("c", multicloud_pools(per_provider=10, baremetal=5))
        env.converge()
        snap = env.telemetry.registry.snapshot()
        rejections = sum(v for (n, _), v in snap.items()
                         if n == "clusterinfra_security_gate_rejections_total")
        self.assertEqual(rejections, 0)


if __name__ == "__main__":
    unittest.main()
