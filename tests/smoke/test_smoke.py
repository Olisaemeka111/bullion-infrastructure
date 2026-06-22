"""Smoke tests — critical-path sanity checks (fast, shallow, run first in CI)."""
import contextlib
import importlib
import io
import json
import os
import tempfile
import unittest

from tests.helpers import make_env, pool, multicloud_pools
from control_plane.models import NodeState, ClusterState

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestImportsSmoke(unittest.TestCase):
    """Every package/module imports cleanly (catches syntax/import breakage)."""

    MODULES = [
        "control_plane.models", "control_plane.state_machine", "control_plane.store",
        "control_plane.reconciler", "control_plane.api",
        "providers.registry", "providers.aws", "providers.gcp",
        "providers.azure", "providers.baremetal",
        "agent.node_agent",
        "security.policy", "security.admission", "security.rbac", "security.hardening",
        "networking.fabric",
        "observability.metrics", "observability.telemetry", "observability.dashboard",
        "workflows.provision", "workflows.drain", "workflows.decommission",
        "workflows.update", "workflows.orchestration",
        "sim.simulate", "sim.multicloud", "sim.observe",
        "cli",
    ]

    def test_all_modules_import(self):
        for m in self.MODULES:
            with self.subTest(module=m):
                importlib.import_module(m)


class TestLifecycleSmoke(unittest.TestCase):
    """The happy path turns on: provision -> HEALTHY -> decommission -> empty."""

    def test_provision_multicloud_to_healthy(self):
        env = make_env()
        env.apply("c", multicloud_pools(per_provider=2, baremetal=1, max_provision=4))
        env.converge(max_ticks=50)
        self.assertEqual(env.healthy(), 2 * 3 + 1)
        self.assertEqual(env.store.clusters["c"].state, ClusterState.ACTIVE)

    def test_decommission_empties_cluster(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 2, max_unavailable=2, max_provision=2)])
        env.converge()
        env.api.decommission_cluster("c")
        ticks = env.converge(max_ticks=50)
        self.assertLess(ticks, 50)
        self.assertEqual(len(list(env.store.all_nodes())), 0)

    def test_security_gate_admits_only_clean_nodes(self):
        env = make_env()
        env.apply("c", [pool("p", "gcp", 3, max_provision=3)])
        env.converge()
        self.assertTrue(all(n.security_passed and n.attested
                            for n in env.nodes(NodeState.HEALTHY)))


class TestObservabilitySmoke(unittest.TestCase):
    def test_metrics_and_dashboard_produce_output(self):
        from observability.dashboard import DashboardData, render_html
        env = make_env()
        env.apply("c", multicloud_pools(per_provider=2, baremetal=1, max_provision=4))
        dash = DashboardData()
        for _ in range(8):
            env.rec.tick()
            dash.capture(len(dash.ticks), env.telemetry, env.store)
        prom = env.telemetry.registry.render_prometheus()
        self.assertIn("clusterinfra_reconcile_ticks_total", prom)
        html = render_html(dash, prom)
        self.assertIn("<!doctype html>", html.lower())


class TestCLISmoke(unittest.TestCase):
    """The clusterctl entrypoint works end-to-end against a temp store."""

    def test_cli_apply_reconcile_status_decommission(self):
        import cli
        tmp = os.path.join(tempfile.mkdtemp(), "state.json")
        orig = cli.STORE_PATH
        cli.STORE_PATH = tmp
        try:
            with contextlib.redirect_stdout(io.StringIO()):  # silence CLI prints
                self.assertEqual(cli.main(["apply", "--cluster", "s", "--pool", "p",
                                           "--provider", "aws", "--type", "x",
                                           "--count", "2", "--max-provision", "2"]), 0)
                self.assertEqual(cli.main(["reconcile"]), 0)
                self.assertEqual(cli.main(["status"]), 0)
                self.assertEqual(cli.main(["decommission", "--cluster", "s"]), 0)
                self.assertEqual(cli.main(["reconcile"]), 0)
        finally:
            cli.STORE_PATH = orig


class TestArtifactsSmoke(unittest.TestCase):
    """Shipped, non-code artifacts exist and parse."""

    def test_grafana_dashboard_is_valid_json(self):
        with open(os.path.join(ROOT, "observability", "grafana_dashboard.json")) as f:
            d = json.load(f)
        self.assertIn("panels", d)
        self.assertGreaterEqual(len(d["panels"]), 8)

    def test_expected_files_present(self):
        for rel in ("README.md", "ARCHITECTURE.md", "RUNBOOK.md", "TESTING.md",
                    "observability/alerts.yml", "observability/SLO.md",
                    "iac/atlantis.yaml", "iac/terraform/main.tf",
                    "workflows/argo_rolling_update.yaml"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)),
                            f"missing artifact: {rel}")


if __name__ == "__main__":
    unittest.main()
