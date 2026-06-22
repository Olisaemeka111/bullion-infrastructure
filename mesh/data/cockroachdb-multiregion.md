# Active-active data: CockroachDB across the 3 clouds

Active-active *traffic* needs active-active *data*, or you split-brain. CockroachDB
is a distributed multi-master SQL database: every region accepts reads **and**
writes, data is replicated with Raft consensus, and the cluster survives losing a
whole region. This pairs with the Istio mesh — CockroachDB nodes in EKS, GKE and
AKS join into one logical database.

## Topology
- One CockroachDB StatefulSet per cluster (3 nodes each → 9 total), each tagged
  with a `--locality` so Cockroach places replicas across clouds (not all in one).
- Nodes join across clouds via the **Istio east-west gateway** (mTLS) or per-node
  LoadBalancer addresses on port 26257.
- `survival goal = region` so the database stays available if one cloud dies.

```
 EKS (aws)        GKE (gcp)        AKS (azure)
 cockroach-0..2   cockroach-0..2   cockroach-0..2
      └──────────── one CockroachDB cluster ───────────┘
        Raft replication, replicas spread across clouds
```

## Install (per cluster)
Use the official Helm chart with a per-cloud values file:

```bash
helm repo add cockroachdb https://charts.cockroachdb.com/
# --- AWS / EKS ---
helm install crdb cockroachdb/cockroachdb --namespace data --create-namespace \
  --context "$CTX_EKS" -f cockroachdb-values-aws.yaml
# --- GCP / GKE ---
helm install crdb cockroachdb/cockroachdb --namespace data --create-namespace \
  --context "$CTX_GKE" -f cockroachdb-values-gcp.yaml
# --- Azure / AKS ---
helm install crdb cockroachdb/cockroachdb --namespace data --create-namespace \
  --context "$CTX_AKS" -f cockroachdb-values-azure.yaml
```

Then initialize once (any cluster):
```bash
kubectl --context "$CTX_EKS" -n data exec -it crdb-cockroachdb-0 -- \
  ./cockroach init --certs-dir=/cockroach/cockroach-certs
```

## Key settings (in each values file)
- `conf.locality: "cloud=<aws|gcp|azure>,region=<region>"`
- `conf.join`: the seed addresses of the OTHER clusters (east-west gateway or LB).
- `statefulset.replicas: 3`
- `tls.enabled: true` (Cockroach mTLS, independent of mesh mTLS).

After init, set the survival goal so a whole-cloud outage is tolerated:
```sql
ALTER DATABASE app SURVIVE REGION FAILURE;
```

## How this completes the active-active story
| Layer | Active-active mechanism |
|---|---|
| North-south traffic | global DNS/GSLB across 3 ingresses (`iac/terraform/modules/global_dns`) |
| East-west traffic | Istio multi-primary global services + locality failover (`mesh/`) |
| **Data** | **CockroachDB multi-region, every cloud read+write, survives region loss** |

> Cross-cloud DB replication adds latency (write quorum spans clouds). Keep
> latency-sensitive tables `REGIONAL BY ROW` so most writes stay local.
