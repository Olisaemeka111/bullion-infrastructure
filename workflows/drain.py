"""Drain workflow: cordon -> evict -> confirm empty.

Always the first half of any safe teardown. A node must pass through DRAINING
before DECOMMISSIONING unless an operator forces it with an approval.
"""
from __future__ import annotations

from control_plane.models import Node, NodeState
from control_plane.state_machine import transition
from agent.node_agent import NodeAgent


def start(node: Node, reason: str = "drain requested") -> None:
    """Move a HEALTHY/FAILED/UPDATING node into DRAINING (idempotent)."""
    if node.state in (NodeState.HEALTHY, NodeState.FAILED, NodeState.UPDATING):
        transition(node, NodeState.DRAINING, reason)


def step(node: Node, pool, provider) -> None:
    if node.state != NodeState.DRAINING:
        return
    agent = NodeAgent(node, pool.image_digest)
    result = agent.drain()
    if result["drained"]:
        transition(node, NodeState.DECOMMISSIONING, "drained, workloads moved")
