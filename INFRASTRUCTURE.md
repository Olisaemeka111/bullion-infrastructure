# Bullion Infrastructure — Project Description & Infrastructure Details

A real, deployed **multi-cloud Kubernetes platform** that runs **AWS EKS and GCP GKE
as a single active-active cluster**, joined by an Istio service mesh with traffic
load-balanced across both clouds — provisioned and operated entirely through
GitHub Actions CI/CD.

- **Repo:** `Olisaemeka111/bullion-infrastructure`
- **Status:** active-active cross-cloud mesh **live and verified** (traffic balances
  EKS⇄GKE). Central database + control-plane container are scaffolded but not yet
  deployed (see §9).

---

## 1. Goal & design

Run compute clusters in more than one cloud and have them behave as **one
active-active platform** — not a primary + cold backup. Concretely:

- A workload deployed to both clouds is reachable as **one global service**.
- Requests are **load-balanced across both clouds** simultaneously.
- If a cloud fails, traffic **automatically redistributes** to the survivor.
- Everything is **infrastructure-as-code + CI/CD**, with keyless auth and gated
  approvals.

```
                 ┌───────────────── one Istio mesh (mesh-fleet) ─────────────────┐
                 │                                                                │
   ┌─────────────▼─────────────┐                        ┌─────────────▼──────────┐
   │  AWS — EKS (bullion-eks)   │   east-west gateways    │  GCP — GKE (bullion-gke)│
   │  us-east-1, 2x m5.xlarge   │◄──────mTLS, BGP────────►│  us-central1-a,         │
   │  istiod (primary)          │   remote-secret join    │  2x e2-standard-4       │
   │  hello (2 pods) + sidecars │                         │  private nodes + NAT    │
   │  network: network-aws      │                         │  istiod (primary)       │
   └─────────────┬─────────────┘                         │  hello (2 pods)         │
                 │                                         │  network: network-gcp  │
                 │   global Service hello.demo.svc          └────────────┬──────────┘
                 │   DestinationRule: 50/50 across regions               │
                 └──────────────── active-active LB ─────────────────────┘
```

---

## 2. Cloud inventory (final state)

### AWS — account `730767193290`, region `us-east-1`
| Resource | Detail |
|---|---|
| EKS cluster | **`bullion-eks`**, Kubernetes **1.32** |
| Node group | 2 × **m5.xlarge** (4 vCPU / 16 GB), on-demand, private subnets |
| Networking | dedicated VPC, 2 AZs, private node subnets + single NAT, public subnets |
| Security | EKS access entries (CI role = cluster-admin; `Olisa` user granted admin); node SG opened for istiod webhook (15017) + xDS (15012) |
| State | S3 bucket `fleet-mini-tfstate-59998ac4`, **native state locking** (no DynamoDB) |

### GCP — project `project-f38bfcd6-70ff-4a8d-9cd`, zone `us-central1-a`
| Resource | Detail |
|---|---|
| GKE cluster | **`bullion-gke`**, **Standard** (zonal), Workload Identity enabled |
| Node pool | 2 × **e2-standard-4** (4 vCPU / 16 GB) |
| Networking | dedicated VPC-native network + subnet (pods/services secondary ranges), **private nodes** (no public IP) + **Cloud NAT** egress |
| Why private nodes | GCP free-trial `IN_USE_ADDRESSES` quota is 4 — private nodes keep node IPs off the count, leaving room for the mesh LoadBalancers |

### Azure
Disabled (`enable_azure=false`). The account has **no subscription** (`NoAzurePlanFound`),
and the azurerm provider/AKS module are commented out until one exists. Re-enabling
is a documented toggle (no redesign).

---

## 3. CI/CD & security

All deploys run through **GitHub Actions** with **keyless OIDC** auth and a gated
`production` environment (required reviewer = you).

| Workflow | Purpose | Trigger |
|---|---|---|
| `ci.yml` | 80 stdlib tests + `terraform fmt/validate` (no cloud creds) | every push/PR |
| `deploy.yml` | Terraform: EKS, GKE, (cross-cloud VPN) — `plan` on PR, gated `apply` on merge, `destroy` on dispatch | PR / push / dispatch |
| `platform.yml` | Istio multi-primary join + global app + observability across both clusters | dispatch / mesh changes |
| `database.yml` | Cross-cloud CockroachDB: discover node IPs → deploy DaemonSet to both clusters → `init` once | dispatch / `mesh/data/**` |
| `game.yml` | Build the board game → push to GHCR → deploy active-active to both clusters | dispatch / `mesh/apps/game.yaml` |

- **AWS auth:** GitHub OIDC → IAM role `fleet-mini-gha` (no static keys).
- **GCP auth:** GitHub OIDC → Workload Identity Federation → service account `fleet-mini-gha`.
- **Secrets:** the deploy identifiers are GitHub Actions secrets/variables (they are
  non-secret OIDC identifiers, not credentials). `iac/generate-credentials.sh` sets
  them via the `gh` CLI. Cloud auth itself is keyless OIDC — no static cloud keys.
- **Remote state:** S3 with native locking; partial backend config supplied at
  `init` time.

---

## 4. Service mesh — final state (Istio multi-primary, multi-network)

The two clusters form **one mesh** (`meshID = mesh-fleet`):

- **Shared root CA** — a common CA issues each cluster's istiod intermediate, so
  workloads in EKS and GKE trust each other's mTLS identities.
- **A primary istiod per cluster** (multi-primary) — each cluster is independently
  controllable; no single control-plane SPOF.
- **East-west gateways** (LoadBalancer) for cross-cluster traffic over mTLS:
  - EKS: `...elb.amazonaws.com`
  - GKE: `136.116.250.171`
- **Remote secrets exchanged** (`istio-remote-secret-eks` / `-gke`) so each istiod
  discovers the other cluster's endpoints.
- **Network labels** — `istio-system` is labelled `topology.istio.io/network=network-aws`
  (EKS) / `network-gcp` (GKE). This is the key that makes cross-network endpoint
  discovery work (without it, traffic stays cluster-local).
- **Global service** `hello.demo.svc.cluster.local` runs in both clusters; a
  `DestinationRule` sets an explicit **50/50 cross-region split** with
  `outlierDetection` for automatic failover.

### Verified active-active behaviour
From a client pod in **EKS**, 20 calls to the global service returned:

```
aws: 12    gcp: 8
```

→ traffic from one cloud is served by **both** clouds through the joined mesh. ✅

---

## 5. Observability

`kube-prometheus-stack` (Prometheus + Grafana + node-exporter) deployed on **EKS**.
GKE uses Google Managed Service for Prometheus (Autopilot/Standard native). A
fleet-wide federated view is described in `mesh/observability/`.

---

## 6. Tasks completed

| # | Task | Outcome |
|---|---|---|
| 1 | Tooling install (gh, terraform, aws, gcloud, az, kubectl, istioctl, hcp) | ✅ |
| 2 | Cloud identities via **OIDC** (AWS role, GCP WIF) | ✅ |
| 3 | Remote state (S3 native locking) | ✅ |
| 4 | CI/CD pipelines (`ci`, `deploy`, `platform`) + gated `production` env | ✅ |
| 5 | Provision **EKS** (VPC, node group) | ✅ |
| 6 | Provision **GKE** | ✅ (Standard, private nodes) |
| 7 | Local `kubectl` access to both clusters | ✅ |
| 8 | **Istio multi-primary** install on both | ✅ |
| 9 | **Join clusters** (CA + east-west + remote secrets + network labels) | ✅ |
| 10 | Global app + **active-active 50/50 LB** | ✅ verified |
| 11 | Observability (Prometheus/Grafana on EKS) | ✅ |
| 12 | Cross-cloud **VPN** module (AWS↔GCP HA VPN + BGP) | ⏳ built, gated off |
| 13 | **CockroachDB** central DB (multi-region over VPN) | ⏳ manifests only |
| 14 | **Control-plane** container (agentic reconciler + dashboard) | ⏳ pending |
| 15 | Global DNS (north-south LB) | ⏳ module built, not applied |

### Notable blockers resolved along the way
- EKS rejected K8s `1.29` → bumped to `1.32`.
- GKE **Autopilot** can't host self-managed Istio / DaemonSets → switched to **Standard**.
- GKE node pool needed **Workload Identity** enabled for `GKE_METADATA`.
- `e2-medium`/`t3.medium` too small for istiod → **4 vCPU/16 GB** nodes.
- GCP free-trial **IP quota (4)** → **private nodes + Cloud NAT**.
- Terraform **state drift** from partial applies → fresh plan reconciled it.
- EKS sidecar-injector webhook timed out → opened **node SG :15017/:15012**.
- Istio `DestinationRule` rejected `distribute`+`failover` together → use `distribute` + `outlierDetection`.
- Cross-cluster traffic stayed local → added the **`topology.istio.io/network`** namespace label.

---

## 7. Offline control-plane model (the design's "brain")

The Python `control_plane/` (reconciler, providers, agent, security gate,
networking model) + `sim/` run fully offline with **80 passing tests**, proving the
agent-driven reconciliation, security gating, and the active-active traffic model
(`networking/global_lb.py`, `sim/active_active.py`). On the real managed clusters,
its responsibilities (provisioning, scaling, self-heal) are fulfilled by Terraform +
managed node groups; the `Provider` interface is the seam to drive real clouds.

---

## 8. Operate it

```bash
# AWS / EKS
aws eks update-kubeconfig --name bullion-eks --region us-east-1 --alias eks
kubectl --context eks get nodes

# GCP / GKE
gcloud container clusters get-credentials bullion-gke --zone us-central1-a --project project-f38bfcd6-70ff-4a8d-9cd
kubectl get nodes

# Verify active-active (from an EKS client pod):
kubectl --context eks -n demo run curl --image=curlimages/curl --restart=Never --command -- sleep 3600
kubectl --context eks -n demo exec curl -c curl -- sh -c \
  "for i in 1 2 3 4 5 6 7 8; do curl -s hello.demo.svc.cluster.local; echo; done"
# -> mix of "hello from aws" and "hello from gcp"
```

- **Deploy/update:** open a PR (plan) → merge (gated apply). Or Actions → run workflow.
- **Tear down:** Actions → `deploy` → Run workflow → `action=destroy` → approve.

---

## 9. What's deployed vs pending

**Live:** EKS + GKE; Istio multi-primary mesh (joined); global app with active-active
cross-cloud LB; observability on EKS; full CI/CD.

**Pending:** cross-cloud VPN (gated off), central **CockroachDB** (the "central
database" — needs the VPN first), control-plane container, global DNS.

---

## 10. Cost & security notes

- 💸 Both clusters + their LoadBalancers bill while running (EKS control plane
  ~$0.10/hr + 2× m5.xlarge; GKE on free credit). Run **`destroy`** when idle.
- 🔑 The AWS access key used for bootstrap was shared in plaintext during setup —
  **rotate it**.
- The `Olisa` IAM user holds `AdministratorAccess` (for local kubectl/EKS access) —
  scope down for anything beyond testing.
- GKE control-plane endpoint is public (open) for CI/local access — restrict with
  authorized networks for production.

---

## 11. Repository layout
```
control_plane/ providers/ agent/ security/ networking/ workflows/ observability/ tests/ sim/
iac/terraform/      EKS + GKE + global_dns + cross_cloud (VPN) modules; S3 backend
mesh/install/       Istio multi-primary (shared CA, IOPs, east-west + ingress, remote secrets)
mesh/apps/          global service + active-active DestinationRule + board game
mesh/observability/ node-exporter DaemonSet + federated Prometheus
mesh/data/          CockroachDB multi-region (cross-cloud, deployed via database.yml)
.github/workflows/  ci.yml · deploy.yml · platform.yml · database.yml · game.yml
DEPLOY.md · CICD.md · ARCHITECTURE.md · RUNBOOK.md · TESTING.md
```
