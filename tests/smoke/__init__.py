"""Smoke tests: fast, shallow 'does the system turn on' checks.

These are the first gate in CI - if any fail, deeper suites are not worth running.
They touch every critical path (imports, provision->HEALTHY, decommission, CLI,
metrics/dashboard, shipped artifacts) but stay tiny and sub-second.
"""
