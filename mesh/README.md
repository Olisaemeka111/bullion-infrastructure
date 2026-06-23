# mesh/ — active-active multi-cloud fabric

Turns the two independent managed clusters (EKS + GKE Standard) into **one
active-active service fabric**: both clouds serve traffic at once, the clusters are
joined and behave as one, and on a cloud outage traffic redistributes to the
survivor automatically — then rebalances on recovery. Not a backup deployment.
(Azure/AKS is an optional third member, disabled by default.)

## The layers

```
        ┌──────────── optional GLOBAL DNS / GSLB (north-south) ─────────────┐
        │  iac/terraform/modules/global_dns — Route53 weighted + health     │
        │  one hostname -> both ingresses active; drops a cloud on failure   │
        └──────────────────┬─────────────────────────┬─────────────────────┘
                  ┌─────────▼─────────┐     ┌──────────▼────────┐
   north-south →  │ istio-ingress LB  │     │  istio-ingress LB │   public :80
                  ├───────────────────┤     ├───────────────────┤
                  │   EKS  (aws)      │ EW  │   GKE  (gcp)      │   Istio
                  │  istiod + EW gw   │◄───►│  istiod + EW gw   │ multi-primary
                  └─────────┬─────────┘     └─────────┬─────────┘ (east-west mTLS)
                            │ global services (board game + hello) span both,
                            │ locality LB 50/50 + outlier-detection failover
                  ┌─────────▼───────────────────────────▼─────────┐
                  │  CockroachDB multi-region — every cloud r+w,   │  data
                  │  Raft replication over the AWS<->GCP VPN,      │  (mesh/data)
                  │  SURVIVE REGION FAILURE                        │
                  └───────────────────────────────────────────────┘
   per-node observability: node-exporter / kube-prometheus-stack on EKS, Google
   Managed Prometheus on GKE, + the Python control-plane telemetry — one fleet view
```

| Layer | Files | What it gives you |
|---|---|---|
| 1. Mesh control plane | `install/iop-*.yaml`, `install/install.sh`, `install/gen-ca.sh` | One mesh (shared root CA), multi-primary istiod per cluster, east-west **and** north-south ingress gateways |
| 2. Active-active apps | `apps/game.yaml`, `apps/hello-global.yaml`, `apps/locality-failover.yaml` | The board game + a hello service, load-balanced 50/50 across both clouds with locality failover |
| 3. Global ingress | each cluster's `istio-ingressgateway` (public LB); optional `../iac/terraform/modules/global_dns` | North-south active-active; optional single DNS name across both ingresses |
| 4. Active-active data | `data/cockroachdb.yaml` | Multi-master CockroachDB across clouds (hostNetwork over the VPN) so writes don't split-brain |
| Observability | `observability/node-exporter-daemonset.yaml`, `observability/prometheus-federation.yaml` | Metrics on **every node** + a federated fleet view |

## How it's deployed — CI/CD

In practice the mesh and workloads are installed by GitHub Actions, not by hand:

| Workflow | Does |
|---|---|
| [`platform.yml`](../.github/workflows/platform.yml) | shared CA + multi-primary Istio + east-west/ingress gateways + remote secrets, the hello service, and observability |
| [`database.yml`](../.github/workflows/database.yml) | discovers node IPs → deploys the CockroachDB DaemonSet to both clusters → `init` once |
| [`game.yml`](../.github/workflows/game.yml) | builds the board game → pushes to GHCR → deploys it active-active behind the ingress gateways |

## Manual install order (equivalent, for reference)
```bash
export CTX_EKS=<ctx> CTX_GKE=<ctx>

cd mesh/install && ./install.sh          # 1. shared CA + multi-primary mesh + gateways
istioctl --context "$CTX_EKS" remote-clusters   # verify both clusters see each other

# 2. deploy the global service(s) to BOTH clusters (set CLOUD per cluster)
for c in EKS GKE; do
  ctx="CTX_$c"; cloud=$(echo $c | tr 'A-Z' 'a-z')
  sed "s/REPLACE_ME/$cloud/" ../apps/hello-global.yaml | kubectl --context "${!ctx}" apply -f -
  kubectl --context "${!ctx}" apply -f ../apps/locality-failover.yaml
done

# 3. observability: kube-prometheus-stack on EKS; GKE uses Google Managed Prometheus
kubectl --context "$CTX_EKS" apply -f ../observability/node-exporter-daemonset.yaml

# 4. active-active data + the game -> see database.yml / game.yml (they fill in the
#    node-IP join list and the GHCR image, so prefer running those workflows).
```

## Verify active-active + failover
```bash
# from a pod in either cluster, hit the global service repeatedly:
kubectl --context "$CTX_EKS" -n demo exec deploy/hello -- \
  sh -c 'for i in 1 2 3 4 5 6 7 8 9 10; do wget -qO- hello.demo.svc.cluster.local; echo; done'
# -> responses come from BOTH aws and gcp (active-active across clouds)

# the board game is reachable at either cluster's ingress LoadBalancer:
kubectl --context "$CTX_EKS" -n istio-system get svc istio-ingressgateway
kubectl --context "$CTX_GKE" -n istio-system get svc istio-ingressgateway

# simulate a cloud outage (scale one cloud's app to 0) and repeat the loop:
kubectl --context "$CTX_GKE" -n demo scale deploy/hello --replicas=0
# -> traffic shifts to aws automatically; restore with --replicas=2
```

The offline model of all this is `python -m sim.active_active` (and the
`networking/global_lb.py` `GlobalTrafficDirector`, unit-tested in
`tests/unit/test_global_lb.py`) — same behavior, proven before you deploy.

## Why GKE Standard (not Autopilot)
GKE was switched from Autopilot to **Standard** because self-managed Istio (and the
hostNetwork CockroachDB DaemonSet) need node/CNI access that Autopilot restricts.
Standard nodes (`e2-standard-4`) host istiod, the gateways and DaemonSets directly.
Node metrics on GKE come from Google Managed Service for Prometheus; EKS runs the
node-exporter DaemonSet + kube-prometheus-stack.
