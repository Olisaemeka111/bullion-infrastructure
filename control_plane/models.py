"""Core domain model: clusters, node pools, nodes, and their lifecycle states.

These dataclasses are the single declarative model. The same model is used for
the *desired* spec (what the operator asks for) and the *observed* state (what
the reconciler sees), which is what makes reconciliation possible.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class NodeState(str, Enum):
    REQUESTED = "REQUESTED"
    PROVISIONING = "PROVISIONING"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    REGISTERING = "REGISTERING"
    HEALTHY = "HEALTHY"
    UPDATING = "UPDATING"
    DRAINING = "DRAINING"
    DECOMMISSIONING = "DECOMMISSIONING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


# A node is "live" if it occupies a real instance we may have to pay for / clean up.
LIVE_STATES = {
    NodeState.PROVISIONING,
    NodeState.BOOTSTRAPPING,
    NodeState.REGISTERING,
    NodeState.HEALTHY,
    NodeState.UPDATING,
    NodeState.DRAINING,
    NodeState.DECOMMISSIONING,
    NodeState.FAILED,
}
TERMINAL_STATES = {NodeState.TERMINATED}


class ClusterState(str, Enum):
    PLANNED = "PLANNED"
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SCALING = "SCALING"
    DRAINING = "DRAINING"
    DECOMMISSIONED = "DECOMMISSIONED"


def _now() -> float:
    return time.time()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass
class Node:
    pool: str
    cluster: str
    provider: str
    instance_type: str
    id: str = field(default_factory=lambda: _id("node"))
    instance_id: Optional[str] = None          # set by provider on create
    state: NodeState = NodeState.REQUESTED
    # homogeneity / provenance signals reported by the agent
    image_digest: Optional[str] = None
    config_hash: Optional[str] = None
    attested: bool = False
    security_passed: bool = False
    # health / heartbeat
    last_heartbeat: float = 0.0
    health: str = "unknown"                     # healthy | degraded | failed | unknown
    # bookkeeping
    reason: str = ""                            # last transition reason
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def touch(self, reason: str = "") -> None:
        self.updated_at = _now()
        if reason:
            self.reason = reason

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class NodePool:
    name: str
    provider: str                  # aws | gcp | azure | baremetal
    instance_type: str
    desired_count: int
    region: str = "us-east-1"
    # safety budget: how many nodes in this pool may be DESTROYED/replaced at once
    max_unavailable: int = 1
    # provisioning concurrency: how many fresh nodes may be created per tick.
    # Decoupled from max_unavailable: bringing capacity online is not destructive,
    # so it can be far more parallel than draining/replacing.
    max_provision: int = 100
    # required image (provenance enforced against this)
    image_digest: str = "sha256:GOLDEN"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Cluster:
    name: str
    pools: dict[str, NodePool] = field(default_factory=dict)
    state: ClusterState = ClusterState.PLANNED
    desired_state: ClusterState = ClusterState.ACTIVE
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "desired_state": self.desired_state.value,
            "pools": {k: v.to_dict() for k, v in self.pools.items()},
            "created_at": self.created_at,
        }
