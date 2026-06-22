"""Decommission workflow: DECOMMISSIONING -> delete instance -> TERMINATED.

Releases the underlying instance and network, then marks the node terminal. The
reconciler garbage-collects TERMINATED nodes from the store.
"""
from __future__ import annotations

from control_plane.models import Node, NodeState
from control_plane.state_machine import transition


def step(node: Node, pool, provider) -> None:
    if node.state != NodeState.DECOMMISSIONING:
        return
    if node.instance_id:
        provider.delete_instance(node.instance_id)  # idempotent
    transition(node, NodeState.TERMINATED, "instance deleted, network released")
