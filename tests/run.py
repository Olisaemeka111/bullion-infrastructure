"""Category-aware test runner (stdlib unittest, zero dependencies).

Usage:
  python -m tests.run            # smoke + unit + integration + chaos (fast subset)
  python -m tests.run smoke      # fast 'does it turn on' gate (run this first)
  python -m tests.run unit
  python -m tests.run integration
  python -m tests.run chaos
  python -m tests.run all        # everything incl. the SLOW 10K-node scale test
  python -m tests.run -v unit    # verbose

The SLOW 10K-node test is skipped unless `all` is selected (which sets
CLUSTERINFRA_RUN_SLOW=1) or the env var is set manually.
"""
from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ordered: smoke runs first as the fast gate
CATEGORIES = {
    "smoke": "tests/smoke",
    "unit": "tests/unit",
    "integration": "tests/integration",
    "chaos": "tests/chaos",
}


def _suite_for(paths):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for p in paths:
        suite.addTests(loader.discover(start_dir=p, top_level_dir=_ROOT))
    return suite


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    verbose = False
    for flag in ("-v", "--verbose"):
        if flag in args:
            verbose = True
            args.remove(flag)

    target = args[0] if args else "default"
    if target == "all":
        os.environ["CLUSTERINFRA_RUN_SLOW"] = "1"
        paths = list(CATEGORIES.values())
    elif target == "default":
        paths = list(CATEGORIES.values())
    elif target in CATEGORIES:
        paths = [CATEGORIES[target]]
    else:
        print(f"unknown category: {target}\nchoose from: {', '.join(CATEGORIES)}, all")
        return 2

    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(_suite_for(paths))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
