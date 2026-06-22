# Cluster Infra — Agent-Driven Cluster Lifecycle Management

End-to-end design + reference implementation for provisioning, operating, and
decommissioning compute clusters across **multiple clouds and on-prem
datacenters**, with **agent-driven automation** and **safe-by-default** behavior.

This document is the design. The runnable reference implementation lives next to
it (Python control plane + node agent + provider abstraction + Terraform stubs +
local simulation). The code is intentionally provider-agnostic so the same
control loop drives AWS, GCP, Azure, and bare-metal.

---

## 1. Goals & non-goals

**Goals**
- One declarative model for a cluster; many backends (cloud + bare metal).
- Fully automated lifecycle: provision → bootstrap → join → operate → drain →
  decommission, with **idempotent, restartable** steps.
- **Safe-by-default**: every destructive action is gated, reversible where
  possible, and rate-limited. Security baselines applied at provision time, not
  bolted on later.
- **Self-healing**: failures detected by agents are reconciled automatically
  (cordon → drain → replace) within blast-radius limits.
- **Homogeneity**: nodes within a pool are bit-for-bit comparable (image
  provenance, config hash, kernel/CNI versions).

**Non-goals (here)**
- Being a real scheduler (Borg/K8s already do this). We manage *nodes and
  clusters*, not pods.
- Production cloud SDK calls — providers are stubbed/simulated so the lifecycle
  logic is testable locally. The interfaces are where real SDK calls slot in.

---

## 2. Control model: declarative spec + reconciliation

The system is a **control loop**, not a script. You declare desired state; the
reconciler drives observed state toward it. This is the single most important
design decision — it is what makes the system idempotent, restartable, and
safe under partial failure.

```
            desired spec (Git / API)
                     │
            ┌────────▼─────────┐
            │   Control Plane  │   reconcile(desired, observed) -> actions
            │   (reconciler)   │◄───────── observed state ──────────┐
            └────────┬─────────┘                                    │
                     │ workflow steps (idempotent)                  │
        ┌────────────┼───────────────┐                             │
        ▼            ▼               ▼                              │
   Provider     Provider        Provider        ... (pluggable)     │
   (AWS)        (GCP)           (BareMetal)                          │
        │            │               │                              │
        ▼            ▼               ▼                              │
     Nodes ───────── Node Agent reports health/state ───────────────┘
```

**Why reconciliation, not a runbook script:** at 10K+ nodes something is always
failing mid-operation. A script that runs steps 1..N breaks if it dies at step 4.
A reconciler re-derives "what's left to do" every tick from observed state, so a
crashed control plane simply resumes. Every action is keyed by a deterministic id
so re-issuing it is a no-op.

---

## 3. Lifecycle state machines

### 3.1 Node lifecycle

```
REQUESTED
   │  provider.create_instance()
   ▼
PROVISIONING ──fail──► FAILED ──┐
   │  instance running          │ (auto-replace policy)
   ▼                            │
BOOTSTRAPPING                   │   agent installs, applies security baseline
   │  agent online + attested   │
   ▼                            │
REGISTERING                     │   join cluster (kubelet/CNI/labels)
   │  node Ready in cluster     │
   ▼                            │
HEALTHY ◄──────────────────┐    │
   │         │             │    │
 update    drain        recover │
   ▼         ▼             │    │
UPDATING   DRAINING ───────┘    │
             │  workloads moved  
             ▼
       DECOMMISSIONING
             │  provider.delete_instance()
             ▼
         TERMINATED ◄────────────┘
```

Allowed transitions are enforced centrally (see `control_plane/state_machine.py`).
Illegal transitions are rejected — you can never `DELETE` a node that hasn't been
`DRAINED` unless an explicit `force` + approval is supplied.

### 3.2 Cluster lifecycle

```
PLANNED → PROVISIONING → ACTIVE ⇄ SCALING
                           │
                           ▼
                       DRAINING → DECOMMISSIONED
```

A cluster owns node *pools* (e.g. `gpu-h100`, `system`). Scaling = creating /
draining nodes in a pool to hit `desired_count`.

---

## 4. Components

### 4.1 Control plane (`control_plane/`)
- `models.py` — `Cluster`, `NodePool`, `Node` dataclasses + enums.
- `state_machine.py` — legal transitions, single source of truth for "can I do X".
- `store.py` — persisted desired+observed state (JSON file here; etcd/Spanner in
  prod), with a monotonic `revision` and crash-safe atomic writes (retried under
  transient Windows/synced-dir file locks).
- `reconciler.py` — the control loop. `reconcile()` is **idempotent** and
  **level-triggered**: given (desired, observed) it computes the minimal set of
  workflow steps and executes them, honoring safety budgets.
- `api.py` — thin command surface (apply spec, get status, request drain).

### 4.2 Provider abstraction (`providers/`)
`base.Provider` is the contract every backend implements:
`create_instance`, `get_instance`, `delete_instance`, `network_attach`,
`apply_security_baseline`. Backends:
- `aws.py`, `gcp.py`, `azure.py` — cloud (EC2 Fleet / Instance Groups / VMSS).
- `baremetal.py` — PXE/iPXE + Redfish/IPMI out-of-band power + image push.
- `registry.py` — maps a pool's `provider` field to an implementation, so the
  reconciler is provider-agnostic. **This is how multi-cloud + on-prem is one
  control loop.**

### 4.3 Node agent (`agent/`)
Runs on every host (systemd unit in prod). Responsibilities:
- **Bootstrap**: install runtime, apply security baseline, write config; report a
  config hash so the control plane can enforce homogeneity.
- **Attestation**: present node identity (SPIFFE/SPIRE-style) over mTLS before it
  is trusted to join. Stubbed here as a signed token.
- **Health**: periodic checks (kubelet, disk, GPU ECC, NIC link, clock skew).
  Publishes `HEALTHY` / `DEGRADED` / `FAILED`.
- **Drain**: on command, cordon and evict workloads, then report drained.

### 4.4 Workflows (`workflows/`)
Long-running, restartable, **idempotent** sequences — the Temporal/Argo analog.
Each step is guarded so re-running is safe:
- `provision.py` — create → wait running → bootstrap → register.
- `update.py` — rolling, respects `max_unavailable`.
- `drain.py` — cordon → drain → confirm empty.
- `decommission.py` — drain → delete instance → release network → forget.

### 4.5 Security (`security/`)
Secure-by-default gate applied **before** a node becomes `HEALTHY`:
- `policy.py` — the node gate: image provenance (cosign-style signature check),
  identity attestation, least-privilege IAM/role, host hardening baseline. A node
  that fails the gate never reaches `HEALTHY`; it goes to `FAILED`.
- `admission.py` — workload admission (validating-webhook analog): Pod Security
  Standards (privileged/baseline/restricted) + supply-chain provenance (signed
  images from trusted registries only).
- `rbac.py` — narrow RBAC roles + least-privilege node IAM; only `break-glass`
  has wildcard, and it requires an approver.
- `hardening.py` — the concrete CIS node/runtime/kubelet baseline behind the
  `cis-baseline-v1` id that `policy.py` validates.

### 4.6 Networking (`networking/`)
`fabric.py` is a declarative, provider-neutral network model the providers
consume in `network_attach()`:
- **Cloud (under-lay)**: VPC/subnets across AZs, Shared VPC, hub attachment
  (Transit Gateway / Network Connectivity Center / Virtual WAN), Interconnect/
  Direct Connect/ExpressRoute, Cloud NAT, BGP ASN + route control, and edge LB +
  DDoS mitigation (Cloud Armor / AWS Shield / Azure DDoS).
- **Host (data-plane)**: Cilium (eBPF) CNI, NetworkPolicy default-deny, multi-NIC
  for GPU hosts (pod/RDMA/storage), sFlow flow export, service mesh + strict mTLS.
- **Cross-cloud**: `CrossCloudMesh` models private, encrypted, BGP-routed
  high-bandwidth inter-cluster links. The Terraform `modules/cross_cloud` mirrors
  it for the static substrate.

`PROVIDER_FABRIC_DEFAULTS` maps the neutral model to each backend's concrete
primitives, so the same fabric description renders correctly per cloud and on-prem.

### 4.7 Observability (`observability/`)
The control plane is instrumented (see `reconciler.py` → `telemetry`):
- `metrics.py` — dependency-free Prometheus registry (counters/gauges/labels,
  real exposition output).
- `telemetry.py` — named metrics + a collector that derives fleet gauges.
- `alerts.yml`, `SLO.md` — alert rules + SLOs/error budgets.
- `grafana_dashboard.json` — 12-panel dashboard; `dashboard.py` renders an
  offline HTML dashboard from a captured run.

---

## 5. Fault tolerance & self-healing

- Agents heartbeat; missing heartbeats past `HEARTBEAT_TIMEOUT` → node marked
  `FAILED` (observed). Agents also report `failed` directly.
- Reconciler reacts to `FAILED` by **auto-replace within a budget**: per-pool
  `max_unavailable` and a global `global_max_replacements` rate limit prevent a
  correlated failure from triggering a stampede that deletes a whole cluster.
- Scale-up uses a separate `max_provision` concurrency (creation is
  non-destructive); scale-down/drain/decommission are the budgeted destructive ops.
- All deletes pass through `DRAINING` unless `force` + approval.
- Reconciler is itself stateless-restartable (state in the store), so a control
  plane crash never loses progress.

---

## 6. Observability & operational excellence

- **Monitoring** (`observability/`): the reconciler emits Prometheus metrics
  (nodes by state, pool availability, provisioning throughput, failures by reason,
  self-heals, security-gate rejections, reconcile ticks). Ships with SLOs, alert
  rules, a Grafana dashboard, and an offline HTML dashboard (`python -m sim.observe`).
- **Operational excellence** (`RUNBOOK.md`): incident response flow,
  drain/decommission procedures, on-call signals, postmortem template. Key
  principle: **every action the automation takes is also a documented manual
  procedure**, so humans and agents share one mental model.

---

## 7. How the pieces map to the JD

| JD responsibility | Where it lives |
|---|---|
| Agent-driven provisioning / updates / decommission | `workflows/`, `agent/`, `reconciler.py` |
| Across all clouds + own datacenters | `providers/` (aws/gcp/azure/baremetal) + `registry.py` |
| High-bandwidth inter-cluster connectivity | `networking/fabric.py` (§4.6) + `iac/terraform/modules/cross_cloud` |
| Cloud + host networking (Cilium/eBPF/mesh/BGP/TGW/...) | `networking/fabric.py`, `network` Terraform module |
| Secure-by-default | `security/policy.py` gate, applied pre-`HEALTHY` |
| Cluster security (PSS/admission, RBAC, hardening, provenance) | `security/{admission,rbac,hardening}.py` |
| Scalability, homogeneity, fault tolerance | reconciler budgets, config-hash homogeneity, self-heal, `sim/multicloud.py` (10K) |
| Monitoring + dashboards | `observability/` |
| Operational excellence / incident / on-call | `RUNBOOK.md` |
| IaC (Terraform, Atlantis), orchestration (Temporal/Argo) | `iac/terraform/`, `iac/atlantis.yaml`, `workflows/orchestration.py`, `workflows/argo_rolling_update.yaml` |
| Testing | `tests/` (unit/integration/chaos) + `TESTING.md` |
