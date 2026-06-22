"""Observed end-to-end run that produces the monitoring dashboards.

Drives the lifecycle tick-by-tick so every transition is captured as time-series,
then writes a self-contained `dashboard.html` and prints a Prometheus scrape.

Story: ramp up a small multi-cloud managed fleet (EKS+GKE+AKS) -> steady state ->
inject a correlated failure wave on one cloud -> watch self-heal recover ->
decommission. Mini scale so it mirrors the real 2-node-per-cloud deployment.

Run:  python -m sim.observe   (then open dashboard.html)
"""
from __future__ import annotations

import os
import time

from control_plane.models import NodePool, NodeState
from control_plane.store import Store
from control_plane.api import ControlPlaneAPI
from control_plane.reconciler import Reconciler
from providers.registry import ProviderRegistry
from observability.dashboard import DashboardData, render_html

# Mini scale: enough nodes per cloud to show a failure wave + self-heal clearly,
# while staying true to the "small managed fleet" shape of the real deployment.
SPEC = [
    ("eks-nodes", "aws", "t3.medium", 10, 3, 10),
    ("gke-nodes", "gcp", "e2-medium", 10, 3, 10),
    ("aks-nodes", "azure", "Standard_D2s_v3", 10, 3, 10),
]


def main() -> None:
    store = Store()
    rec = Reconciler(store, ProviderRegistry())
    api = ControlPlaneAPI(store)
    dash = DashboardData()

    api.apply_cluster("fleet-prod", [
        NodePool(name=n, provider=p, instance_type=t, desired_count=c,
                 max_unavailable=mu, max_provision=mp, image_digest="sha256:GOLD-v1")
        for (n, p, t, c, mu, mp) in SPEC
    ])

    def tick(label: str | None = None):
        rec.tick()
        dash.capture(len(dash.ticks), rec.telemetry, store)
        if label:
            dash.event(label)

    # 1. ramp to steady state
    dash.event("apply spec")
    for _ in range(20):
        tick()
        if all(p.desired_count <= len([n for n in store.nodes_in_pool("fleet-prod", p.name)
               if n.state == NodeState.HEALTHY]) for p in store.clusters["fleet-prod"].pools.values()):
            break
    tick("steady state")

    # 2. steady ticks
    for _ in range(3):
        tick()

    # 3. inject a correlated failure wave on one provider
    victims = [n for n in store.all_nodes()
               if n.state == NodeState.HEALTHY and n.provider == "gcp"][:5]
    for v in victims:
        api.report_health(v.id, "failed", time.time())
    dash.event(f"inject {len(victims)} gke (gcp) failures")

    # 4. self-heal recovery
    for _ in range(25):
        tick()
        healthy = len([n for n in store.all_nodes() if n.state == NodeState.HEALTHY])
        if healthy >= sum(s[3] for s in SPEC):
            break
    tick("recovered")

    # 5. decommission
    api.decommission_cluster("fleet-prod")
    dash.event("decommission")
    for _ in range(60):
        tick()
        if not list(store.all_nodes()):
            break
    tick("decommissioned")

    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard.html")
    html = render_html(dash, rec.telemetry.registry.render_prometheus())
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"captured {len(dash.ticks)} ticks")
    print("events: " + ", ".join(f"{e['label']}@t{e['tick']}" for e in dash.events))
    print(f"dashboard written: {out}")
    print("\n--- Prometheus scrape (first 25 lines) ---")
    print("\n".join(rec.telemetry.registry.render_prometheus().splitlines()[:25]))


if __name__ == "__main__":
    main()
