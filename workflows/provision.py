"""Provision workflow: REQUESTED -> ... -> HEALTHY.

Advances a node by one stage per call. Every stage is idempotent and guarded by
the central state machine, so re-entry after a crash is safe.
"""
from __future__ import annotations

from control_plane.models import Node, NodeState, NodePool
from control_plane.state_machine import transition
from providers.base import Provider
from agent.node_agent import NodeAgent
from security import policy


def step(node: Node, pool: NodePool, provider: Provider) -> None:
    if node.state == NodeState.REQUESTED:
        inst = provider.create_instance(
            node.id, node.instance_type, pool.region, pool.image_digest)
        if inst.status == "failed":
            transition(node, NodeState.FAILED, "instance create failed")
            return
        node.instance_id = inst.instance_id
        transition(node, NodeState.PROVISIONING, "instance running")
        return

    if node.state == NodeState.PROVISIONING:
        # apply infra-layer security baseline + network attach
        baseline = provider.apply_security_baseline(node.instance_id)
        provider.network_attach(node.instance_id, node.cluster)
        node._baseline = baseline  # transient, used by next stage
        transition(node, NodeState.BOOTSTRAPPING, "baseline+network applied")
        return

    if node.state == NodeState.BOOTSTRAPPING:
        agent = NodeAgent(node, pool.image_digest)
        boot = agent.bootstrap()
        node.config_hash = boot["config_hash"]
        node.image_digest = pool.image_digest
        node.attested = bool(agent.attest())
        transition(node, NodeState.REGISTERING, "bootstrapped + attested")
        return

    if node.state == NodeState.REGISTERING:
        # secure-by-default gate: must pass before HEALTHY
        baseline = getattr(node, "_baseline", {})
        result = policy.evaluate(node, baseline, pool.image_digest)
        if not result.passed:
            transition(node, NodeState.FAILED,
                       "security gate: " + "; ".join(result.failures))
            return
        node.security_passed = True
        transition(node, NodeState.HEALTHY, "registered + admitted")
        return
