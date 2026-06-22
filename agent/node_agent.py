"""Node agent.

In production this is a small Go/Rust binary shipped as a systemd unit on every
host. It is the "agent" in agent-driven automation: it bootstraps the host,
attests its identity to the control plane over mTLS, continuously reports health,
and executes drain commands. Here it is a Python object the simulator drives, but
the responsibilities and the report shape mirror the real thing.
"""
from __future__ import annotations

import hashlib
import time


class NodeAgent:
    def __init__(self, node, image_digest: str):
        self.node = node
        self.image_digest = image_digest
        self._cordoned = False

    # ---- bootstrap ------------------------------------------------------
    def bootstrap(self) -> dict:
        """Install runtime + write config; produce a config hash used to enforce
        homogeneity across a pool (two nodes with the same hash are identical)."""
        config = {
            "kubelet": "v1.30.0",
            "cni": "cilium-1.15",
            "kernel": "6.6-hardened",
            "image_digest": self.image_digest,
        }
        config_hash = hashlib.sha256(
            repr(sorted(config.items())).encode()
        ).hexdigest()[:16]
        return {"config": config, "config_hash": config_hash}

    # ---- attestation ----------------------------------------------------
    def attest(self) -> str:
        """Return a signed node identity (SPIFFE/SPIRE-style SVID). The control
        plane verifies this before the node is allowed to register/join. Stubbed
        as a deterministic token derived from the node id."""
        return "spiffe://cluster/" + hashlib.sha256(
            self.node.id.encode()).hexdigest()[:24]

    # ---- health ---------------------------------------------------------
    def health_report(self) -> dict:
        """Health signals the failure detector consumes. A real agent checks
        kubelet readiness, disk pressure, GPU ECC errors, NIC link, clock skew."""
        checks = {
            "kubelet_ready": True,
            "disk_ok": True,
            "gpu_ecc_ok": True,
            "nic_link_up": True,
            "clock_skew_ok": True,
        }
        status = "healthy" if all(checks.values()) else "degraded"
        if self._cordoned:
            status = "draining"
        return {"status": status, "checks": checks, "ts": time.time()}

    # ---- drain ----------------------------------------------------------
    def cordon(self) -> None:
        self._cordoned = True

    def drain(self) -> dict:
        """Evict workloads. Returns once the node holds no workloads."""
        self._cordoned = True
        return {"cordoned": True, "evicted_workloads": 0, "drained": True}
