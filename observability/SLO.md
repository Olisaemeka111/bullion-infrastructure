# Service Level Objectives — Cluster Infra

SLOs are the contract between Cluster Infra and its consumers (research,
inference, product). Alerts in `alerts.yml` fire against these.

| SLO | Objective | Indicator (metric) | Error budget |
|---|---|---|---|
| **Fleet availability** | ≥ 99% of desired nodes HEALTHY per pool | `clusterinfra_pool_availability_ratio` | 1% (≈ allowed degraded fraction) |
| **Provisioning latency** | New node REQUESTED→HEALTHY p95 ≤ target | derived from create/advance actions | tracked per provider |
| **Self-heal time** | FAILED→replaced HEALTHY p95 within budget window | `clusterinfra_self_heal_total` + availability recovery | — |
| **Secure-by-default** | 100% of HEALTHY nodes passed the gate | `clusterinfra_security_gate_rejections_total` == 0 admitted | zero tolerance |
| **Control-plane liveness** | Reconciler ticks continuously | `clusterinfra_reconcile_ticks_total` rate > 0 | zero tolerance |

## Error-budget policy
- If a pool burns its availability budget, **freeze rolling updates** for that
  pool (stop introducing voluntary disruption) until it recovers.
- Security and control-plane liveness SLOs have **zero** error budget — any
  violation pages immediately and blocks further automation that depends on them.

## Why these
They map 1:1 to what the consumers actually feel: enough healthy capacity, brought
online fast, recovered automatically, never insecure, and a control plane that is
always making progress.
