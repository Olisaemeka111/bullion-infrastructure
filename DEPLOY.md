# DEPLOY.md — provisioning the mini managed-K8s fleet to the cloud

This deploys real managed Kubernetes clusters. **They cost money.** Each cloud has
an independent `enable_<cloud>` switch so you can start with one. Always
`terraform destroy` when finished.

---

## 1. Prerequisites

| Tool | Used for |
|---|---|
| Terraform ≥ 1.5 | provisioning |
| `aws` CLI | EKS auth + `update-kubeconfig` |
| `gcloud` CLI | GKE auth + `get-credentials` |
| `az` CLI | AKS auth + `get-credentials` |
| `kubectl` | verifying the clusters |

**Authenticate to each cloud you enable** (these set the credentials Terraform and
the kubeconfig commands use):
```bash
# AWS
aws configure                 # or export AWS_PROFILE / AWS_ACCESS_KEY_ID etc.

# GCP  (Autopilot)
gcloud auth application-default login
gcloud config set project <YOUR_PROJECT_ID>
gcloud services enable container.googleapis.com compute.googleapis.com

# Azure
az login
# (azurerm uses your active az subscription)
```

---

## 2. Configure

```bash
cd iac/terraform
cp terraform.tfvars.example terraform.tfvars
```
Edit `terraform.tfvars`:
- Set `gcp_project` (required if `enable_gcp = true`).
- Flip `enable_aws` / `enable_gcp` / `enable_azure` to choose clouds.
- Adjust regions / node sizes if desired. `node_count` defaults to **2** (applies
  to EKS + AKS; GKE Autopilot manages nodes itself).

---

## 3. Provision

```bash
terraform init        # downloads providers + the EKS/VPC modules
terraform plan        # review what will be created
terraform apply       # type 'yes' — EKS/AKS ~10-15 min, GKE Autopilot ~5-8 min
```

> **Cost tip:** to validate the flow cheaply, set only `enable_aws = true` first,
> apply, verify, `destroy`, then repeat for the others.

---

## 4. Get kubeconfig & verify

Terraform prints the exact command per cloud (`terraform output`). For example:
```bash
# AWS / EKS
aws eks update-kubeconfig --region us-east-1 --name fleet-mini-eks
kubectl get nodes -o wide          # expect 2 Ready t3.medium nodes

# GCP / GKE Autopilot
gcloud container clusters get-credentials fleet-mini-gke --region us-central1 --project <PROJECT>
kubectl get nodes -o wide          # nodes appear as workloads are scheduled

# Azure / AKS
az aks get-credentials --resource-group fleet-mini-aks-rg --name fleet-mini-aks
kubectl get nodes -o wide          # expect 2 Ready Standard_D2s_v3 nodes
```

A quick smoke test on any cluster:
```bash
kubectl create deployment hello --image=nginx --replicas=2
kubectl expose deployment hello --port=80 --type=LoadBalancer
kubectl get svc hello -w           # wait for an EXTERNAL-IP
kubectl delete svc/hello deploy/hello
```

---

## 5. What gets created (networking is provisioned per cloud)

| Cloud | Cluster | Networking |
|---|---|---|
| AWS | EKS + managed node group (2× t3.medium) | dedicated VPC, 2 AZs, private node subnets + 1 NAT, public subnets, EKS subnet tags |
| GCP | GKE **Autopilot** (regional) | dedicated VPC-native network + subnet, secondary ranges (pods/services), Dataplane V2 |
| Azure | AKS + default node pool (2× D2s_v3) | dedicated VNet + subnet, Azure CNI + Calico network policy, system-assigned identity |

This mirrors the provider-neutral `networking/fabric.py` model: VPC/VNet + subnets,
CNI/eBPF dataplane, network policy, and managed identity / least-privilege roles.

---

## 5b. Join the clusters into one active-active fabric

Once all three clusters are up and you have a kubeconfig context for each, turn
them into one active-active mesh (see **[mesh/README.md](mesh/README.md)** for the
full detail):

```bash
export CTX_EKS=<ctx> CTX_GKE=<ctx> CTX_AKS=<ctx>
cd mesh/install && ./install.sh            # shared CA + Istio multi-primary + east-west
istioctl --context "$CTX_EKS" remote-clusters   # all 3 should see each other

# deploy the global active-active service to every cluster, then verify traffic
# is served from all clouds and fails over when one is scaled to zero.
```

Then layer on: per-node observability (`mesh/observability/`), the active-active
CockroachDB datastore (`mesh/data/`), and global DNS
(`iac/terraform/modules/global_dns`). The offline equivalent is
`python -m sim.active_active`.

## 6. Tear down (do this!)

```bash
terraform destroy     # removes clusters + all networking it created
```
If you used per-cloud switches, destroy removes whatever is currently enabled.
Double-check the cloud consoles afterward (especially load balancers / disks
created by `kubectl`, which Terraform does not manage).

---

## 7. Optional — PR-driven deploys (Atlantis)

`iac/atlantis.yaml` wires the same GitOps flow as the reference project: open a PR
touching `iac/terraform/**`, Atlantis comments the `plan`, a reviewer approves, and
`atlantis apply` provisions. Requires a running Atlantis server with cloud creds.

---

## 8. Troubleshooting

- **`gcp_project` empty** → set it in `terraform.tfvars` (required for GKE).
- **K8s version not available** → adjust `kubernetes_version` (EKS/AKS) to a
  version supported in your region; GKE Autopilot ignores it (release channel).
- **EKS auth denied with kubectl** → the apply identity is granted cluster-admin
  (`enable_cluster_creator_admin_permissions`); re-run `update-kubeconfig` with the
  same identity that ran `terraform apply`.
- **Quota errors** → medium instances + 1 NAT are modest, but new accounts may
  need a vCPU/address quota bump in the chosen region.
