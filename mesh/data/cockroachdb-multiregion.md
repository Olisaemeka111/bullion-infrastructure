# Active-active data: CockroachDB across the clouds

Active-active *traffic* needs active-active *data*, or you split-brain. CockroachDB
is a distributed multi-master SQL database: every region accepts reads **and**
writes, data is replicated with Raft consensus, and the cluster survives losing a
whole region. This pairs with the Istio mesh — CockroachDB nodes in EKS and GKE
join into one logical database. (Azure/AKS would be a third member if enabled.)

## How it's actually deployed (this project)
The live manifest is [`cockroachdb.yaml`](cockroachdb.yaml), applied by the
[`database.yml`](../../.github/workflows/database.yml) workflow.

- **DaemonSet, not StatefulSet** — one CockroachDB node per Kubernetes node
  (2 in EKS + 2 in GKE = **4 nodes total**).
- **`hostNetwork: true`** — each pod advertises its routable **node IP**, because
  pod IPs are not routable cross-cloud. CRDB nodes gossip node-to-node on
  `26257` across the **AWS↔GCP HA VPN** (`iac/terraform/modules/cross_cloud`).
- **`--join`** is the list of every node IP (`<ip>:26257`); `database.yml` discovers
  the live node IPs from both clusters and fills the list in — never hand-maintained.
- **Insecure mode** for this cross-cloud validation; enabling TLS (cert-manager or
  `cockroach cert`) is the production-hardening step.
- Image `cockroachdb/cockroach:v24.3.5`; in-cluster SQL via the
  `cockroachdb-public` Service in namespace `data`.

```
 EKS (aws, us-east-1)            GKE (gcp, us-central1-a)
 crdb on node 10.10.8.117        crdb on node 10.20.0.9
 crdb on node 10.10.17.85        crdb on node 10.20.0.10
      └──────── one CockroachDB cluster (4 nodes) ────────┘
        Raft replication over the AWS<->GCP VPN; replicas spread across clouds
```

## Deploy
Prefer the workflow (it builds the join list + runs init once, idempotently):
```bash
gh workflow run database.yml          # or push a change under mesh/data/
```
Equivalent by hand:
```bash
# build the join list from live node IPs, apply to both clusters
JOIN=$(kubectl --context eks get nodes -o jsonpath='{.items[*].status.addresses[?(@.type=="InternalIP")].address}';
       kubectl --context gke get nodes -o jsonpath='{.items[*].status.addresses[?(@.type=="InternalIP")].address}')
JOIN=$(echo $JOIN | tr ' ' '\n' | sort -u | sed 's/$/:26257/' | paste -sd, -)
for ctx in eks gke; do sed "s|__JOIN__|$JOIN|g" cockroachdb.yaml | kubectl --context $ctx apply -f -; done
# initialize once (any node)
pod=$(kubectl --context eks -n data get pod -l app=cockroachdb -o jsonpath='{.items[0].metadata.name}')
kubectl --context eks -n data exec "$pod" -- /cockroach/cockroach init --insecure --host=localhost:26257
```

## Production hardening (next steps)
- **TLS**: switch `--insecure` for `cockroach cert`/cert-manager-issued node + client certs.
- **Survival goal** (once databases use multi-region): `ALTER DATABASE app SURVIVE REGION FAILURE;`
  and keep latency-sensitive tables `REGIONAL BY ROW` so most writes stay local.

## How this completes the active-active story
| Layer | Active-active mechanism |
|---|---|
| North-south traffic | each cluster's Istio ingress gateway (public LB); optional global DNS across both (`iac/terraform/modules/global_dns`) |
| East-west traffic | Istio multi-primary global services + locality failover (`mesh/`) |
| **Data** | **CockroachDB multi-region, every cloud read+write, survives region loss** |

> Cross-cloud DB replication adds latency (write quorum spans clouds). Keep
> latency-sensitive tables `REGIONAL BY ROW` so most writes stay local.
