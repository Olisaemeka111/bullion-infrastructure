"""Mini multi-cloud managed-Kubernetes deployment (the shape the real Terraform
provisions).

Declares the SAME fleet the IaC deploys — 2 medium managed nodes in each of EKS,
GKE and AKS (6 nodes, 3 clouds) — in one declarative spec and reconciles it to
HEALTHY, proving the control logic end-to-end offline before you spend a cent in
the cloud.

    AWS   (EKS)  2 x t3.medium
    GCP   (GKE)  2 x e2-medium
    Azure (AKS)  2 x Standard_D2s_v3
                 ----------------------
                 6 managed nodes, 3 clusters

Run:  python -m sim.multicloud
Then deploy for real:  see iac/terraform + DEPLOY.md
"""
from __future__ import annotations

import json
import time

from control_plane.models import NodePool, NodeState
from control_plane.store import Store
from control_plane.api import ControlPlaneAPI
from control_plane.reconciler import Reconciler
from providers.registry import ProviderRegistry

# Mirrors iac/terraform/terraform.tfvars: 2 medium nodes per managed cluster.
#   name        provider  instance_type        count  max_unavail  max_provision
SPEC = [
    ("eks-nodes", "aws",   "t3.medium",         2,     1,           2),
    ("gke-nodes", "gcp",   "e2-medium",         2,     1,           2),
    ("aks-nodes", "azure", "Standard_D2s_v3",   2,     1,           2),
]


def build_pools() -> list[NodePool]:
    return [
        NodePool(name=n, provider=p, instance_type=t, desired_count=c,
                 max_unavailable=mu, max_provision=mp, image_digest="sha256:GOLD-v1")
        for (n, p, t, c, mu, mp) in SPEC
    ]


def main() -> None:
    store = Store()
    registry = ProviderRegistry(failure_rate=0.0)
    api = ControlPlaneAPI(store)
    rec = Reconciler(store, registry)

    total = sum(s[3] for s in SPEC)
    print(f"Provisioning {total} managed nodes across {len(SPEC)} clouds "
          f"(EKS + GKE + AKS), 2 medium nodes each\n")

    api.apply_cluster("fleet-mini", build_pools())

    t0 = time.time()
    ticks = rec.run_until_converged(max_ticks=200)
    elapsed = time.time() - t0

    by_provider: dict[str, dict[str, int]] = {}
    for n in store.all_nodes():
        d = by_provider.setdefault(n.provider, {})
        d[n.state.value] = d.get(n.state.value, 0) + 1

    print(f"converged in {ticks} ticks / {elapsed:.3f}s\n")
    print(json.dumps(by_provider, indent=2))

    healthy = [n for n in store.all_nodes() if n.state == NodeState.HEALTHY]
    secure = sum(1 for n in healthy if n.security_passed and n.attested)
    print(f"\nHEALTHY: {len(healthy)}/{total}")
    print(f"passed security gate + attested: {secure}/{len(healthy)}")
    print(f"cluster state: {store.clusters['fleet-mini'].state.value}")


if __name__ == "__main__":
    main()
