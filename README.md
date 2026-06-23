# cluster-infra-mini

A **deployable miniature** of the [`cluster-infra`](../cluster-infra) reference
design: the exact same agent-driven, reconciliation-based control plane, security
gate, networking model, observability and test suite — but scaled to a small,
real, multi-cloud **managed-Kubernetes** fleet you can actually stand up in the
cloud:

| Cloud | Managed service | Nodes | Size |
|---|---|---|---|
| AWS | **EKS** (managed node group) | 2 | `m5.xlarge` |
| GCP | **GKE Standard** (zonal, private nodes) | 2 | `e2-standard-4` |
| Azure | **AKS** (optional — disabled by default) | 2 | `Standard_D2s_v3` |

The Python control plane is **identical in design** to the reference project and
runs fully offline (simulated providers) to prove the lifecycle logic before you
spend a cent. The `iac/terraform/` tree is **real, `terraform validate`-clean
HCL** that provisions the managed clusters + networking for actual cloud testing.

The clusters are **joined into one active-active fabric** (`mesh/`): both clouds
serve traffic at once, and on a cloud outage traffic redistributes to the survivor
automatically — Istio multi-primary (east-west + north-south ingress) +
CockroachDB (multi-master data over an AWS↔GCP VPN) + optional global DNS. The
Python node **agent** and **per-node observability** stay in place across clouds.

## Two layers, one model

```
            ┌─────────────────────────────────────────────┐
 offline    │  Python control plane (same as cluster-infra)│   python -m sim.multicloud
 (proves    │  reconciler · security gate · self-heal ·    │   python -m tests.run all
  the logic)│  networking model · observability · 74 tests │
            └─────────────────────────────────────────────┘
                         declares the same fleet
            ┌─────────────────────────────────────────────┐
 real       │  iac/terraform  →  EKS + GKE Standard (+AKS) │   terraform apply
 (deploys   │  per-cloud VPC/VNet + subnets + node pools   │   kubectl get nodes
  to cloud) └─────────────────────────────────────────────┘
```

## Layout
```
control_plane/  providers/  agent/  security/  networking/  workflows/
observability/  tests/  sim/  cli.py            # same design as cluster-infra
iac/terraform/                                   # REAL deployable IaC
  main.tf versions.tf variables.tf outputs.tf terraform.tfvars.example
  modules/eks/   (terraform-aws-modules VPC + EKS, 2x m5.xlarge)
  modules/gke/   (GKE Standard zonal, private nodes + Cloud NAT, VPC-native)
  modules/aks/   (VNet + AKS, 2x Standard_D2s_v3 — optional, off by default)
  modules/cross_cloud/ (AWS<->GCP HA VPN + BGP for the central database)
  modules/global_dns/  (Route53 active-active across the ingresses)
iac/atlantis.yaml                                # PR-driven plan/apply
mesh/                                            # ACTIVE-ACTIVE fabric (joins the 3 clusters)
  install/    Istio multi-primary (shared CA, east-west gateways, remote secrets)
  apps/       global service + locality-aware load balancing + failover
  observability/  per-node node-exporter DaemonSet + federated Prometheus
  data/       CockroachDB multi-region (multi-master, survive region failure)
DEPLOY.md  CICD.md                               # deploy + CI/CD (incl. secret) guides
```

## Quickstart — prove the logic offline (no cloud, no deps)
```bash
# the mini fleet the IaC deploys: 3 managed clouds, reconciled to HEALTHY
python -m sim.multicloud

# full lifecycle: provision -> rolling update -> self-heal -> decommission
python -m sim.simulate

# ACTIVE-ACTIVE: balance traffic across all clouds, then survive a cloud outage
python -m sim.active_active

# observed run -> writes dashboard.html
python -m sim.observe

# the test suite (same design as the reference + the active-active traffic model)
python -m tests.run all
```

## Deploy for real (managed K8s in the cloud)
See **[DEPLOY.md](DEPLOY.md)** for the full walk-through. In short:
```bash
cd iac/terraform
cp terraform.tfvars.example terraform.tfvars   # set gcp_project; toggle clouds
terraform init
terraform plan
terraform apply
# then use the printed kubeconfig commands, e.g.:
aws eks update-kubeconfig --region us-east-1 --name bullion-eks
kubectl get nodes -o wide                        # 2 Ready m5.xlarge nodes
```
Each cloud has an `enable_<cloud>` switch so you can deploy **one at a time** to
limit cost. Tear everything down with `terraform destroy`.

### Or deploy via CI/CD (GitHub Actions)
For repeatable, approval-gated deploys, [.github/workflows/deploy.yml](.github/workflows/deploy.yml)
runs `plan` on every PR (commented on the PR), `apply` on merge to `main` (gated by
a `production` environment), and `destroy` on manual dispatch — with **keyless OIDC
auth** to all three clouds (no static cloud keys). One-time setup (remote state +
OIDC) is in **[CICD.md](CICD.md)**.

### Secret management
Cloud auth is **keyless OIDC** — no static cloud keys exist. The only values stored
are the non-sensitive OIDC **identifiers** (AWS role ARN, GCP Workload Identity
provider + service account), held as **GitHub Actions secrets** and read by the
workflows via `secrets.*`. `iac/generate-credentials.sh` creates the cloud OIDC
resources and sets these secrets/variables in one go via the `gh` CLI — see
**[CICD.md](CICD.md)**.

## How this maps to the reference design
The architecture, lifecycle state machines, safety budgets, security gate,
networking fabric and operational runbook are unchanged — see the copied
[`ARCHITECTURE.md`](ARCHITECTURE.md), [`RUNBOOK.md`](RUNBOOK.md) and
[`TESTING.md`](TESTING.md). The only differences are deployment-facing:

| Aspect | cluster-infra (reference) | cluster-infra-mini (this) |
|---|---|---|
| Scale | up to 10,000 simulated nodes | 2× 4-vCPU nodes per cloud (real) |
| Backends | aws/gcp/azure/bare-metal (simulated) | EKS / GKE Standard (+ optional AKS), real IaC |
| IaC | illustrative stubs | real, `validate`-clean, deployable |
| Purpose | prove design at scale, offline | test an actual cloud deployment |
| Control plane | identical | identical |
| Tests | 74, all green | 74, all green |

## Active-active, not backup
Both clouds serve traffic concurrently and the fleet behaves as one:
- **East-west** (service→service): Istio multi-primary *global services* with
  locality-aware load balancing + outlier-detection failover (`mesh/`).
- **North-south** (user→app): each cluster's Istio ingress gateway serves the app
  (the board game); an optional global DNS layer
  (`iac/terraform/modules/global_dns`) fronts both ingresses health-checked.
- **Data**: CockroachDB multi-region, every cloud read+write, survives region loss.
- **On a cloud outage** traffic redistributes to the survivor automatically and
  rebalances on recovery — modeled and tested offline by `sim.active_active` +
  `networking/global_lb.py` (`GlobalTrafficDirector`).

The Python **node agent** (bootstrap/attest/health/drain) and **per-node
observability** (node-exporter DaemonSet + Istio signals + control-plane
telemetry) remain across both clouds — see `mesh/observability/`.

## Status (verified)
- **Tests: 80, all green** (`smoke 8 + unit 43 + integration 24 + chaos 5`).
- **Simulations run clean** — `sim.multicloud` (6/6 HEALTHY across 3 clouds),
  `sim.simulate`, `sim.active_active` (balance → outage → redistribute → recover),
  `sim.observe` (writes `dashboard.html`).
- **IaC valid** — `terraform validate` → "Success!"; `terraform fmt` clean;
  `terraform init` resolves all providers/modules.

> Cloud resources cost money. Always `terraform destroy` after testing. EKS and
> GKE Standard bill per node + control plane; the cross-cloud VPN + LoadBalancers
> add a little more.
