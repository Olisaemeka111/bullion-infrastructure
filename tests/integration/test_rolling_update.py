"""Integration: rolling update respects budget and keeps the pool homogeneous."""
import unittest

from tests.helpers import (make_env, pool, assert_system_invariants,
                           assert_homogeneous)
from control_plane.models import NodeState


class TestRollingUpdate(unittest.TestCase):
    def test_all_nodes_reach_new_image(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 6, max_unavailable=2, max_provision=6,
                             image="sha256:GOLD-v1")])
        env.converge()
        # Declare the new image ONCE, then let the reconciler roll the pool. This
        # is the real (level-triggered) contract: a one-shot desired-state change
        # must converge on its own — no per-tick re-plan loop.
        env.api.rolling_update("c", "p", "sha256:GOLD-v2")
        env.converge()
        healthy = env.nodes(NodeState.HEALTHY)
        self.assertEqual(len(healthy), 6)
        self.assertTrue(all(n.image_digest == "sha256:GOLD-v2" for n in healthy))
        assert_homogeneous(self, env, "c", "p")

    def test_rolling_update_is_level_triggered(self):
        # Regression guard: setting the image once and reconciling must fully
        # migrate the pool. (The earlier edge-triggered impl left all but
        # max_unavailable nodes stranded on the old image here.)
        env = make_env()
        env.apply("c", [pool("p", "aws", 5, max_unavailable=1, max_provision=5,
                             image="sha256:GOLD-v1")])
        env.converge()
        self.assertEqual(env.api.rolling_update("c", "p", "sha256:GOLD-v2"), 5)
        env.converge()
        healthy = env.nodes(NodeState.HEALTHY)
        self.assertEqual(len(healthy), 5)
        self.assertTrue(all(n.image_digest == "sha256:GOLD-v2" for n in healthy))

    def test_budget_never_exceeded_during_update(self):
        env = make_env()
        env.apply("c", [pool("p", "aws", 8, max_unavailable=2, max_provision=8,
                             image="sha256:GOLD-v1")])
        env.converge()
        # declare the update once, then assert the invariant holds at every tick
        # while the reconciler rolls the pool.
        env.api.rolling_update("c", "p", "sha256:GOLD-v2")
        for _ in range(80):
            env.rec.tick()
            assert_system_invariants(self, env)
        healthy = env.nodes(NodeState.HEALTHY)
        self.assertTrue(all(n.image_digest == "sha256:GOLD-v2" for n in healthy))


if __name__ == "__main__":
    unittest.main()
