"""Test suite for cluster-infra.

Layout:
  tests/unit/         fast, isolated tests of single modules (no control loop)
  tests/integration/  end-to-end tests that drive the reconciler control loop
  tests/chaos/        fault-injection + randomized property/invariant tests
  tests/helpers.py    shared fixtures, builders, and invariant assertions

Run everything with the category-aware runner:  python -m tests.run all
or with stdlib discovery:                        python -m unittest discover -s tests
"""
import os
import sys

# make the project root importable regardless of where tests are run from
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
