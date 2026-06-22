"""clusterctl — operator CLI over the control plane.

A thin, scriptable surface for the same operations on-call engineers and the
automation use. State persists to a JSON store file so commands compose across
invocations.

Examples:
  python cli.py apply  --cluster research-prod --pool gpu --provider aws \\
                       --type p5.48xlarge --count 3
  python cli.py reconcile
  python cli.py status
  python cli.py update  --cluster research-prod --pool gpu --image sha256:GOLD-v2
  python cli.py drain   --node node-abc123 --approved-by alice
  python cli.py decommission --cluster research-prod
"""
from __future__ import annotations

import argparse
import json

from control_plane.models import NodePool
from control_plane.store import Store
from control_plane.api import ControlPlaneAPI
from control_plane.reconciler import Reconciler
from providers.registry import ProviderRegistry

STORE_PATH = "clusterctl-state.json"


def _ctx():
    store = Store(STORE_PATH)
    api = ControlPlaneAPI(store)
    rec = Reconciler(store, ProviderRegistry())
    return store, api, rec


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="clusterctl")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("apply", help="declare/extend a cluster pool")
    a.add_argument("--cluster", required=True)
    a.add_argument("--pool", required=True)
    a.add_argument("--provider", required=True,
                   choices=["aws", "gcp", "azure", "baremetal"])
    a.add_argument("--type", required=True)
    a.add_argument("--count", type=int, required=True)
    a.add_argument("--image", default="sha256:GOLD-v1")
    a.add_argument("--max-unavailable", type=int, default=1)
    a.add_argument("--max-provision", type=int, default=100,
                   help="how many fresh nodes may be created per reconcile tick")

    sub.add_parser("reconcile", help="run reconcile to convergence")
    sub.add_parser("status", help="print cluster/pool status")

    u = sub.add_parser("update", help="rolling update a pool to a new image")
    u.add_argument("--cluster", required=True)
    u.add_argument("--pool", required=True)
    u.add_argument("--image", required=True)

    d = sub.add_parser("decommission", help="decommission a whole cluster")
    d.add_argument("--cluster", required=True)

    fd = sub.add_parser("force-drain", help="emergency node teardown (audited)")
    fd.add_argument("--node", required=True)
    fd.add_argument("--approved-by", required=True)

    args = p.parse_args(argv)
    store, api, rec = _ctx()

    if args.cmd == "apply":
        api.apply_cluster(args.cluster, [NodePool(
            name=args.pool, provider=args.provider, instance_type=args.type,
            desired_count=args.count, image_digest=args.image,
            max_unavailable=args.max_unavailable,
            max_provision=args.max_provision)])
        print(f"applied {args.cluster}/{args.pool}")
    elif args.cmd == "reconcile":
        ticks = rec.run_until_converged()
        print(f"converged in {ticks} ticks")
    elif args.cmd == "status":
        print(json.dumps(api.status(), indent=2))
    elif args.cmd == "update":
        api.rolling_update(args.cluster, args.pool, args.image)
        print(f"rolling update planned for {args.cluster}/{args.pool} -> {args.image}")
    elif args.cmd == "decommission":
        api.decommission_cluster(args.cluster)
        print(f"decommission requested for {args.cluster}")
    elif args.cmd == "force-drain":
        api.force_decommission_node(args.node, args.approved_by)
        print(f"forced teardown of {args.node} (approved by {args.approved_by})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
