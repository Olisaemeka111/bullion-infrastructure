# Cluster Infra — Operational Runbook

Operational-excellence companion to `ARCHITECTURE.md`. Principle: **every action
the automation takes is also a documented manual procedure**, so humans and
agents share one mental model. The control plane is the primary operator; humans
intervene only to change desired state or to authorize a forced bypass.

---

## 1. On-call signals (what pages, and why)

| Signal | Source | Severity | Auto-response |
|---|---|---|---|
| Pool below desired healthy count | reconciler | high if > max_unavailable | scale-up within budget |
| Node heartbeat timeout | agent / control plane | medium | mark FAILED → drain → replace |
| Provisioning failure rate spike | provider | high | back off creates; page |
| Security gate rejections | `security/policy.py` | high | node → FAILED; do **not** admit |
| Reconciler producing no progress | control plane | high | page; suspect stuck dependency |
| Global replacement budget saturated | reconciler | critical | page; likely correlated failure |

A page should almost always be about *desired state can't be reached*, not about
a single node — single nodes self-heal.

---

## 2. Standard procedures

### 2.1 Bring up a new cluster
1. Land the Terraform substrate PR (Atlantis plan → review → apply): network
   fabric, security groups, per-pool launch templates.
2. `clusterctl apply --cluster <c> --pool <p> --provider <aws|gcp|azure|baremetal> --type <t> --count <n>`
3. `clusterctl reconcile` (or let the running control plane converge).
4. Verify `clusterctl status` shows the cluster `ACTIVE` and pools at desired
   healthy count.

### 2.2 Rolling update (new golden image)
1. Confirm the new image is signed / provenance-verified.
2. `clusterctl update --cluster <c> --pool <p> --image <digest>`
3. Watch `status`: stale HEALTHY nodes drain and are replaced, never exceeding
   `max_unavailable` in flight. Pool stays at desired healthy count throughout.

### 2.3 Drain / decommission a node (safe path)
- Normal: the reconciler does this automatically on FAILED.
- Manual: there is no "delete node" — you change desired state (scale down) or
  fail it. Both route through `DRAINING → DECOMMISSIONING → TERMINATED`.

### 2.4 Emergency node teardown (bypass drain)
Use only when a node is actively harmful (compromised, corrupting data):
```
clusterctl force-drain --node <id> --approved-by <you>
```
This bypasses the drain guard and is recorded with the approver in the node's
`reason` for the postmortem. Never script this against many nodes.

### 2.5 Decommission a whole cluster
```
clusterctl decommission --cluster <c>
clusterctl reconcile
```
All pools drain, instances are deleted, network released, nodes GC'd, cluster →
`DECOMMISSIONED`.

---

## 3. Incident response flow

1. **Detect** — page fires from a signal in §1.
2. **Stabilize** — if a correlated failure is tripping the global replacement
   budget, that budget is *protecting you*: do not raise it blindly, or you risk
   stampede-deleting healthy capacity. First confirm the failures are real.
3. **Diagnose** — `clusterctl status`; inspect node `reason` fields and agent
   health reports. Determine: provider-side (capacity/quota), image/security
   gate, or networking.
4. **Mitigate** — change desired state (pause updates, pin image, cordon a
   provider) rather than hand-editing nodes.
5. **Recover** — let the reconciler converge; verify desired == observed.
6. **Postmortem** — see §4.

### Safe-by-default guardrails to remember under pressure
- `max_unavailable` (per pool) and `global_max_replacements` cap blast radius.
- No node reaches HEALTHY without passing the security gate.
- No node is deleted without draining unless force + approver is supplied.
- The reconciler is idempotent/restartable — restarting the control plane is
  always safe and never loses progress.

---

## 4. Postmortem template

```
## Summary
What broke, customer/research impact, duration.

## Timeline (UTC)
detect → page → mitigate → recover, with the key reconciler actions.

## Root cause
The single underlying cause (not the symptom).

## What worked / what didn't
Did budgets contain blast radius? Did self-heal behave? Did a guard get bypassed?

## Action items (owner, date)
- Prevention (make the failure impossible or auto-handled)
- Detection (page sooner / with better signal)
- Mitigation (faster/safer recovery)
```

Blameless. The most valuable action items convert a manual recovery step into an
automated, budgeted reconciler behavior.

---

## 5. Capacity ingestion (new compute coming online)

1. Physical/cloud build-out completes; capacity registered with provider.
2. Terraform substrate extended for the new region/datacenter.
3. Pool `desired_count` raised; reconciler provisions within budget on schedule.
4. Verify homogeneity: all new nodes report the same `config_hash` and golden
   `image_digest` as the rest of the pool.
