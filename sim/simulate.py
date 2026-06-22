"""End-to-end local simulation of the full cluster lifecycle (mini, managed K8s).

Demonstrates, with no cloud access, the whole arc the real Terraform deployment
will exercise on EKS + GKE + AKS:
  provision (3 managed clouds) -> operate -> rolling update -> inject failure ->
  self-heal -> decommission.

Run:  python -m sim.simulate
"""
from __future__ import annotations

import time

from control_plane.models import NodePool, NodeState
from control_plane.store import Store
from control_plane.api import ControlPlaneAPI
from control_plane.reconciler import Reconciler
from providers.registry import ProviderRegistry


def banner(msg: str) -> None:
    print("\n" + "=" * 72 + f"\n{msg}\n" + "=" * 72)


def show(api: ControlPlaneAPI) -> None:
    import json
    print(json.dumps(api.status(), indent=2))


def main() -> None:
    store = Store()
    registry = ProviderRegistry(failure_rate=0.0)
    api = ControlPlaneAPI(store)
    rec = Reconciler(store, registry)

    banner("1. APPLY CLUSTER SPEC  (managed K8s: EKS + GKE + AKS, 2 medium nodes each)")
    api.apply_cluster("fleet-mini", [
        NodePool("eks-nodes", provider="aws", instance_type="t3.medium",
                 desired_count=2, max_unavailable=1, image_digest="sha256:GOLD-v1"),
        NodePool("gke-nodes", provider="gcp", instance_type="e2-medium",
                 desired_count=2, max_unavailable=1, image_digest="sha256:GOLD-v1"),
        NodePool("aks-nodes", provider="azure", instance_type="Standard_D2s_v3",
                 desired_count=2, max_unavailable=1, image_digest="sha256:GOLD-v1"),
    ])
    show(api)

    banner("2. RECONCILE TO DESIRED STATE  (provision -> bootstrap -> admit -> HEALTHY)")
    ticks = rec.run_until_converged()
    print(f"converged in {ticks} ticks")
    show(api)

    banner("3. ROLLING UPDATE  eks-nodes -> GOLD-v2 (honors max_unavailable budget)")
    # Level-triggered: declare the new desired image once, then let the reconciler
    # roll the whole pool to it within max_unavailable — no re-plan loop needed.
    api.rolling_update("fleet-mini", "eks-nodes", "sha256:GOLD-v2")
    ticks = rec.run_until_converged()
    print(f"rolled in {ticks} ticks")
    show(api)
    imgs = {n.image_digest for n in store.nodes_in_pool("fleet-mini", "eks-nodes")
            if n.state == NodeState.HEALTHY}
    print(f"eks-nodes healthy images now: {imgs}")

    banner("4. INJECT FAILURE  (agent reports a node FAILED) -> SELF-HEAL")
    victim = [n for n in store.nodes_in_pool("fleet-mini", "gke-nodes")
              if n.state == NodeState.HEALTHY][0]
    print(f"marking {victim.id} as failed")
    api.report_health(victim.id, "failed", time.time())
    ticks = rec.run_until_converged()
    print(f"self-healed in {ticks} ticks")
    show(api)

    banner("5. DECOMMISSION CLUSTER  (drain everything, release, terminate)")
    api.decommission_cluster("fleet-mini")
    ticks = rec.run_until_converged()
    print(f"decommissioned in {ticks} ticks")
    show(api)
    print(f"live nodes remaining: {len([n for n in store.all_nodes()])}")


if __name__ == "__main__":
    main()
