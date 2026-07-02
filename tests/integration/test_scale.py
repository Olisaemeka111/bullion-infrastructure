"""Integration: scale behavior. The heavy 10K case is tagged SLOW and skipped
unless CLUSTERINFRA_RUN_SLOW=1 (or via `python -m tests.run scale`)."""
import os
import time
import unittest

from tests.helpers import make_env, multicloud_pools, pool, assert_system_invariants

RUN_SLOW = os.environ.get("CLUSTERINFRA_RUN_SLOW") == "1"


class TestScale(unittest.TestCase):
    def test_mid_scale_multicloud_converges(self):
        env = make_env()
        env.apply("fleet", multicloud_pools(per_provider=200, baremetal=100,
                                             max_unavailable=50, max_provision=400))
        ticks = env.converge()
        self.assertEqual(env.healthy(), 200 * 3 + 100)
        self.assertLess(ticks, 60)
        assert_system_invariants(self, env)

    @unittest.skipUnless(RUN_SLOW, "set CLUSTERINFRA_RUN_SLOW=1 for the 10K case")
    def test_ten_thousand_nodes(self):
        env = make_env(global_max_replacements=500)
        env.apply("fleet", [
            pool("aws", "aws", 3000, max_unavailable=50, max_provision=1000),
            pool("gcp", "gcp", 3000, max_unavailable=50, max_provision=1000),
            pool("azure", "azure", 3000, max_unavailable=50, max_provision=1000),
            pool("metal", "baremetal", 1000, max_unavailable=25, max_provision=1000),
        ])
        t0 = time.time()
        env.converge()
        self.assertEqual(env.healthy(), 10000)
        self.assertLess(time.time() - t0, 30)  # must stay fast


if __name__ == "__main__":
    unittest.main()
