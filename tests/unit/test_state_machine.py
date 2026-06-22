"""Unit: lifecycle state machine transition rules."""
import unittest

from control_plane.models import Node, NodeState
from control_plane.state_machine import (transition, can_transition,
                                          IllegalTransition, NODE_TRANSITIONS)


def node(state=NodeState.REQUESTED):
    n = Node(pool="p", cluster="c", provider="aws", instance_type="t")
    n.state = state
    return n


class TestTransitions(unittest.TestCase):
    def test_happy_path_allowed(self):
        path = [NodeState.REQUESTED, NodeState.PROVISIONING, NodeState.BOOTSTRAPPING,
                NodeState.REGISTERING, NodeState.HEALTHY]
        for a, b in zip(path, path[1:]):
            self.assertTrue(can_transition(a, b), f"{a}->{b} should be allowed")

    def test_idempotent_self_transition_is_noop(self):
        n = node(NodeState.HEALTHY)
        transition(n, NodeState.HEALTHY)  # no raise
        self.assertEqual(n.state, NodeState.HEALTHY)

    def test_illegal_skip_rejected(self):
        with self.assertRaises(IllegalTransition):
            transition(node(NodeState.HEALTHY), NodeState.TERMINATED)
        with self.assertRaises(IllegalTransition):
            transition(node(NodeState.REQUESTED), NodeState.HEALTHY)

    def test_force_requires_approver(self):
        n = node(NodeState.HEALTHY)
        with self.assertRaises(IllegalTransition):
            transition(n, NodeState.DECOMMISSIONING, force=True)
        transition(n, NodeState.DECOMMISSIONING, force=True, approved_by="alice")
        self.assertEqual(n.state, NodeState.DECOMMISSIONING)
        self.assertIn("FORCED by alice", n.reason)

    def test_terminal_state_has_no_exits(self):
        self.assertEqual(NODE_TRANSITIONS[NodeState.TERMINATED], set())

    def test_failed_can_only_drain_or_decommission(self):
        self.assertEqual(NODE_TRANSITIONS[NodeState.FAILED],
                         {NodeState.DRAINING, NodeState.DECOMMISSIONING})


if __name__ == "__main__":
    unittest.main()
