"""Durable workflow orchestration — Temporal-style definition.

The reconciler is the level-triggered controller; for long, multi-step
operations that must survive process restarts and have visibility/retries
(bring-up of a brand-new cluster, a fleet-wide rolling update, a coordinated
decommission), we model them as durable workflows. This mirrors the Temporal
programming model: a deterministic *workflow* function orchestrates idempotent
*activities*, each with its own retry policy; Temporal persists progress so a
crash resumes exactly where it left off.

Here the activities delegate to the same idempotent functions the reconciler
uses, so there is one implementation of each step regardless of who drives it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetryPolicy:
    initial_interval_s: float = 1.0
    backoff: float = 2.0
    max_attempts: int = 10


@dataclass
class ActivityResult:
    name: str
    ok: bool
    detail: str = ""


# ---- activities (idempotent units of work, each independently retried) -----
def activity_apply_terraform(cluster: str) -> ActivityResult:
    """Apply the static substrate (network, launch templates) via Atlantis."""
    return ActivityResult("apply_terraform", True, f"substrate ready for {cluster}")


def activity_scale_pool(api, cluster: str, pool: str, count: int) -> ActivityResult:
    api.scale_pool(cluster, pool, count)
    return ActivityResult("scale_pool", True, f"{cluster}/{pool}={count}")


def activity_reconcile_to_ready(rec, max_ticks: int = 500) -> ActivityResult:
    ticks = rec.run_until_converged(max_ticks=max_ticks)
    return ActivityResult("reconcile_to_ready", True, f"converged in {ticks} ticks")


def activity_verify_homogeneity(store, cluster: str) -> ActivityResult:
    """Assert every healthy node in a pool shares one config hash + image."""
    from control_plane.models import NodeState
    for pname, pool in store.clusters[cluster].pools.items():
        hashes = {n.config_hash for n in store.nodes_in_pool(cluster, pname)
                  if n.state == NodeState.HEALTHY}
        if len(hashes) > 1:
            return ActivityResult("verify_homogeneity", False,
                                  f"{pname} not homogeneous: {hashes}")
    return ActivityResult("verify_homogeneity", True, "all pools homogeneous")


# ---- workflows (deterministic orchestration of activities) -----------------
@dataclass
class WorkflowRun:
    name: str
    results: list[ActivityResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def step(self, result: ActivityResult) -> "WorkflowRun":
        self.results.append(result)
        return self


def cluster_bringup_workflow(api, rec, store, cluster: str) -> WorkflowRun:
    """Durable bring-up: substrate -> provision -> converge -> verify."""
    wf = WorkflowRun(name=f"bringup:{cluster}")
    wf.step(activity_apply_terraform(cluster))
    wf.step(activity_reconcile_to_ready(rec))
    wf.step(activity_verify_homogeneity(store, cluster))
    return wf


def cluster_decommission_workflow(api, rec, cluster: str) -> WorkflowRun:
    """Durable teardown: request decommission -> reconcile until empty."""
    wf = WorkflowRun(name=f"decommission:{cluster}")
    api.decommission_cluster(cluster)
    wf.step(activity_reconcile_to_ready(rec))
    return wf
