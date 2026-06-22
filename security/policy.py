"""Secure-by-default admission gate.

A node must pass *every* check before the reconciler will transition it to
HEALTHY. If any check fails the node is moved to FAILED and replaced. This is how
"secure-by-default" becomes a property of the system rather than a checklist:
there is no code path that admits an un-attested, un-hardened, or
unverified-image node into a cluster.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PolicyResult:
    passed: bool
    failures: list[str]


def evaluate(node, baseline: dict, expected_image: str) -> PolicyResult:
    failures: list[str] = []

    # 1. supply-chain / image provenance (cosign-style signature check)
    if node.image_digest != expected_image:
        failures.append(
            f"image provenance: got {node.image_digest}, want {expected_image}")

    # 2. identity attestation must be present (mTLS / SPIFFE SVID)
    if not node.attested:
        failures.append("node not attested (no valid SVID)")

    # 3. least-privilege IAM/role applied at infra layer
    if not baseline.get("least_privilege"):
        failures.append("instance role is not least-privilege")

    # 4. host hardening baseline applied
    if baseline.get("host_hardening") != "cis-baseline-v1":
        failures.append("host hardening baseline missing")

    return PolicyResult(passed=not failures, failures=failures)
