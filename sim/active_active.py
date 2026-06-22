"""Active-active multi-cloud traffic distribution (offline model).

Proves the behavior you asked for, end-to-end and offline:
  1. join 3 clouds (EKS + GKE Autopilot + AKS) into one fleet and reconcile to HEALTHY,
  2. confirm the Python node agent + observability are live on EVERY node,
  3. balance live traffic across ALL clouds at once (active-active, not backup),
  4. inject a CLOUD OUTAGE and watch traffic redistribute to the survivors,
  5. recover and watch it rebalance.

Run:  python -m sim.active_active
"""
from __future__ import annotations

from control_plane.models import NodePool, NodeState
from control_plane.store import Store
from control_plane.api import ControlPlaneAPI
from control_plane.reconciler import Reconciler
from providers.registry import ProviderRegistry
from networking.global_lb import GlobalTrafficDirector
from agent.node_agent import NodeAgent

CLUSTER = "fleet-mini"
SPEC = [
    ("eks-nodes", "aws", "t3.medium", 2),
    ("gke-nodes", "gcp", "e2-medium", 2),
    ("aks-nodes", "azure", "Standard_D2s_v3", 2),
]
REQUESTS = 12000


def bar(weights: dict, width: int = 40) -> None:
    for cloud in ("aws", "gcp", "azure"):
        w = weights.get(cloud, 0.0)
        print(f"   {cloud:<6} {'#' * int(w * width):<{width}} {w*100:5.1f}%")


def show_distribution(gtd: GlobalTrafficDirector, down=None) -> None:
    d = gtd.distribute(REQUESTS, down=down)
    bar(d.weights)
    print(f"   requests routed: {d.allocation}")
    print(f"   serving clouds : {d.serving_clouds}"
          + (f"   |  DRAINED (outage): {d.drained_clouds}" if d.drained_clouds else ""))


def main() -> None:
    store = Store()
    rec = Reconciler(store, ProviderRegistry())
    api = ControlPlaneAPI(store)
    gtd = GlobalTrafficDirector(store, CLUSTER)

    print("== 1. JOIN 3 CLOUDS INTO ONE ACTIVE-ACTIVE FLEET ==")
    api.apply_cluster(CLUSTER, [
        NodePool(name=n, provider=p, instance_type=t, desired_count=c,
                 max_unavailable=1, max_provision=c, image_digest="sha256:GOLD-v1")
        for (n, p, t, c) in SPEC])
    rec.run_until_converged()
    healthy = [x for x in store.all_nodes() if x.state == NodeState.HEALTHY]
    print(f"   HEALTHY nodes across fleet: {len(healthy)}\n")

    print("== 2. PYTHON AGENT + OBSERVABILITY LIVE ON EVERY NODE ==")
    for n in sorted(healthy, key=lambda x: (x.provider, x.id)):
        agent = NodeAgent(n, n.image_digest)
        hr = agent.health_report()
        print(f"   {n.provider:<6} {n.id}  agent={hr['status']:<8} "
              f"attested={'Y' if n.attested else 'N'} "
              f"cfg={n.config_hash}  gate={'pass' if n.security_passed else 'FAIL'}")
    rec.tick()  # refresh telemetry gauges (observability collects from every node)
    print("   observability (clusterinfra_pool_healthy_nodes by cloud): "
          + str(gtd.capacity_by_cloud()))
    print("   -> every node reports agent health + is scraped for metrics\n")

    print(f"== 3. BALANCE {REQUESTS} REQUESTS ACROSS ALL CLOUDS (active-active) ==")
    show_distribution(gtd)
    print()

    print("== 4. CLOUD OUTAGE: AWS goes down -> traffic redistributes ==")
    show_distribution(gtd, down={"aws"})
    print("   (no manual failover: AWS weight -> 0, GCP+Azure absorb the load)\n")

    print("== 5. AWS RECOVERS -> fleet rebalances ==")
    show_distribution(gtd)


if __name__ == "__main__":
    main()
