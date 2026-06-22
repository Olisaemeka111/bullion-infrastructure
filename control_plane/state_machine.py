"""Legal lifecycle transitions, enforced centrally.

This is the single source of truth for "is this transition allowed". Every code
path that changes a node's state goes through `transition()`, so an illegal jump
(e.g. HEALTHY -> TERMINATED without draining) is impossible unless explicitly
forced with approval.
"""
from __future__ import annotations

from .models import NodeState

# desired-state-machine: state -> set of states reachable in one step
NODE_TRANSITIONS: dict[NodeState, set[NodeState]] = {
    NodeState.REQUESTED: {NodeState.PROVISIONING, NodeState.FAILED},
    NodeState.PROVISIONING: {NodeState.BOOTSTRAPPING, NodeState.FAILED},
    NodeState.BOOTSTRAPPING: {NodeState.REGISTERING, NodeState.FAILED},
    NodeState.REGISTERING: {NodeState.HEALTHY, NodeState.FAILED},
    NodeState.HEALTHY: {
        NodeState.UPDATING,
        NodeState.DRAINING,
        NodeState.FAILED,
    },
    NodeState.UPDATING: {NodeState.HEALTHY, NodeState.FAILED, NodeState.DRAINING},
    # A failed node is recovered by draining then replacing it.
    NodeState.FAILED: {NodeState.DRAINING, NodeState.DECOMMISSIONING},
    NodeState.DRAINING: {NodeState.DECOMMISSIONING, NodeState.FAILED},
    NodeState.DECOMMISSIONING: {NodeState.TERMINATED, NodeState.FAILED},
    NodeState.TERMINATED: set(),
}

# Transitions that destroy/replace capacity and therefore need a safety budget.
DESTRUCTIVE = {NodeState.DRAINING, NodeState.DECOMMISSIONING, NodeState.TERMINATED}


class IllegalTransition(Exception):
    pass


def can_transition(src: NodeState, dst: NodeState) -> bool:
    return dst in NODE_TRANSITIONS.get(src, set())


def transition(node, dst: NodeState, reason: str = "", *, force: bool = False,
               approved_by: str | None = None) -> None:
    """Mutate node.state if the transition is legal.

    Forced transitions (e.g. emergency teardown) require an explicit approver so
    there is always an audit trail for why a safe-by-default guard was bypassed.
    """
    if node.state == dst:
        return  # idempotent: re-issuing a transition is a no-op
    if not can_transition(node.state, dst):
        if not force:
            raise IllegalTransition(
                f"{node.id}: {node.state.value} -> {dst.value} is not allowed"
            )
        if not approved_by:
            raise IllegalTransition(
                f"{node.id}: forced {node.state.value} -> {dst.value} requires approved_by"
            )
        reason = f"FORCED by {approved_by}: {reason}"
    node.state = dst
    node.touch(reason)
