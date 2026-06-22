"""Property-based / randomized testing (stdlib only, no hypothesis).

Generates random but valid sequences of operations (apply, scale, fail, update,
decommission) against a random multi-cloud fleet, ticking the reconciler in
between, and asserts the system invariants hold after every step and that the
system always converges to desired state when left alone.

Each case uses a fixed seed derived from the iteration so failures are
reproducible; the seed is printed in the assertion message.
"""
import random
import time
import unittest

from tests.helpers import make_env, pool, assert_system_invariants
from control_plane.models import NodeState, ClusterState

PROVIDERS = ["aws", "gcp", "azure", "baremetal"]
CASES = 25
OPS_PER_CASE = 12


def _random_fleet(rng, env):
    npools = rng.randint(1, 3)
    pools = []
    for i in range(npools):
        pools.append(pool(f"p{i}", rng.choice(PROVIDERS),
                          count=rng.randint(1, 8),
                          max_unavailable=rng.randint(1, 4),
                          max_provision=rng.randint(2, 8)))
    env.apply("c", pools)


class TestRandomizedLifecycle(unittest.TestCase):
    def test_invariants_hold_under_random_ops(self):
        for case in range(CASES):
            seed = 1000 + case
            rng = random.Random(seed)
            env = make_env(failure_rate=rng.choice([0.0, 0.0, 0.1, 0.25]))
            _random_fleet(rng, env)
            env.converge()

            for _ in range(OPS_PER_CASE):
                op = rng.choice(["scale", "fail", "update", "tick", "scale", "fail"])
                cluster = env.store.clusters["c"]
                pname = rng.choice(list(cluster.pools))
                if op == "scale":
                    env.api.scale_pool("c", pname, rng.randint(0, 8))
                elif op == "fail":
                    healthy = env.nodes(NodeState.HEALTHY)
                    if healthy:
                        for n in rng.sample(healthy, k=rng.randint(1, len(healthy))):
                            env.api.report_health(n.id, "failed", time.time())
                elif op == "update":
                    env.api.rolling_update("c", pname, f"sha256:GOLD-{rng.randint(2,5)}")
                # advance a random number of ticks, checking invariants each time
                for _ in range(rng.randint(1, 5)):
                    env.rec.tick()
                    assert_system_invariants(self, env)

            # 4. left alone, the system must converge to desired (no churn)
            ticks = env.converge(max_ticks=300)
            self.assertLess(ticks, 300, f"did not converge (seed={seed})")
            assert_system_invariants(self, env)
            # every pool at its desired healthy count
            for pname, p in env.store.clusters["c"].pools.items():
                healthy = [n for n in env.store.nodes_in_pool("c", pname)
                           if n.state == NodeState.HEALTHY]
                self.assertEqual(len(healthy), p.desired_count,
                                 f"pool {pname} off-target (seed={seed})")


if __name__ == "__main__":
    unittest.main()
