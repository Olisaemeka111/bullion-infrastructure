# mesh/ — active-active multi-cloud fabric

Turns the three independent managed clusters (EKS + GKE Autopilot + AKS) into **one
active-active service fabric**: all clouds serve traffic at once, the clusters are
joined and behave as one, and on a cloud outage traffic redistributes to the
survivors automatically — then rebalances on recovery. Not a backup deployment.

## The four layers

```
        ┌──────────────── GLOBAL DNS / GSLB (north-south) ────────────────┐
        │  iac/terraform/modules/global_dns — Route53 weighted + health    │
        │  one hostname -> all 3 ingresses active; drops a cloud on failure │
        └──────┬─────────────────────┬─────────────────────┬──────────────┘
        ┌──────▼──────┐       ┌───────▼──────┐       ┌───────▼──────┐
        │  EKS (aws)  │  mesh │ GKE Autopilot│  mesh │  AKS (azure) │
        │ istiod + EW │◄─────►│ istiod + EW  │◄─────►│ istiod + EW  │   Istio
        │  gateway    │       │   gateway    │       │   gateway    │ multi-primary
        └──────┬──────┘       └──────┬───────┘       └──────┬───────┘ (east-west)
               │  global service `hello` spans all 3, locality LB + failover
        ┌──────▼─────────────────────▼──────────────────────▼──────────┐
        │   CockroachDB multi-region — every cloud read+write, Raft      │  data
        │   replication, SURVIVE REGION FAILURE                          │
        └───────────────────────────────────────────────────────────────┘
   per-node observability: node-exporter DaemonSet on every node + Istio golden
   signals + the Python control-plane telemetry, federated into one fleet view
```

| Layer | Files | What it gives you |
|---|---|---|
| 1. Mesh control plane | `install/iop-*.yaml`, `install/install.sh`, `install/gen-ca.sh` | One mesh (shared root CA), multi-primary istiod per cluster, east-west gateways |
| 2. Active-active app | `apps/hello-global.yaml`, `apps/locality-failover.yaml` | A global service load-balanced across all clouds with locality failover |
| 3. Global ingress | `../iac/terraform/modules/global_dns` | North-south active-active across the 3 ingresses, health-checked |
| 4. Active-active data | `data/cockroachdb-*` | Multi-master DB so writes don't split-brain |
| Observability | `observability/node-exporter-daemonset.yaml`, `observability/prometheus-federation.yaml` | Metrics on **every node** + a federated fleet view |

## Install order (after `terraform apply` + kubeconfigs)
```bash
export CTX_EKS=<ctx> CTX_GKE=<ctx> CTX_AKS=<ctx>

cd mesh/install && ./install.sh          # 1. shared CA + multi-primary mesh
istioctl --context "$CTX_EKS" remote-clusters   # verify all 3 see each other

# 2. deploy the global service to ALL clusters (set CLOUD per cluster)
for c in EKS GKE AKS; do
  ctx="CTX_$c"; cloud=$(echo $c | tr 'A-Z' 'a-z')
  sed "s/REPLACE_ME/$cloud/" ../apps/hello-global.yaml | kubectl --context "${!ctx}" apply -f -
  kubectl --context "${!ctx}" apply -f ../apps/locality-failover.yaml
done

# 3. per-node observability (EKS/AKS; Autopilot uses managed Prometheus)
kubectl --context "$CTX_EKS" apply -f ../observability/node-exporter-daemonset.yaml
kubectl --context "$CTX_AKS" apply -f ../observability/node-exporter-daemonset.yaml

# 4. active-active data
#    see data/cockroachdb-multiregion.md

# 5. global DNS  -> terraform apply the global_dns module with the ingress hostnames
```

## Verify active-active + failover
```bash
# from a pod in any cluster, hit the global service repeatedly:
kubectl --context "$CTX_EKS" -n demo exec deploy/hello -- \
  sh -c 'for i in $(seq 20); do wget -qO- hello.demo.svc.cluster.local; echo; done'
# -> responses come from aws, gcp AND azure (active-active across clouds)

# simulate a cloud outage (scale one cloud's app to 0) and repeat:
kubectl --context "$CTX_GKE" -n demo scale deploy/hello --replicas=0
# -> traffic shifts to aws + azure automatically; restore with --replicas=2
```

The offline model of all this is `python -m sim.active_active` (and the
`networking/global_lb.py` `GlobalTrafficDirector`, unit-tested in
`tests/unit/test_global_lb.py`) — same behavior, proven before you deploy.

## Note on GKE Autopilot
Istio runs fine on Autopilot (ordinary workloads). The only Autopilot limitation
is host-privileged DaemonSets: use **Google Managed Service for Prometheus** for
GKE node metrics instead of the node-exporter DaemonSet; EKS and AKS use the
DaemonSet. The mesh, global services and failover are identical on all three.
