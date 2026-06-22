"""Provider contract.

Every backend (cloud or bare metal) implements this interface. The reconciler and
workflows only ever talk to `Provider`, never to a specific cloud SDK. This is the
seam that makes "multi-cloud + on-prem" a single control loop instead of three
parallel codebases.

All methods MUST be idempotent and keyed by the logical node id, because the
reconciler may retry any of them after a crash.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Instance:
    instance_id: str
    status: str            # provisioning | running | stopped | gone
    private_ip: str = ""


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def create_instance(self, node_id: str, instance_type: str, region: str,
                        image_digest: str) -> Instance:
        """Create (or return existing) instance for this logical node id."""

    @abstractmethod
    def get_instance(self, instance_id: str) -> Instance:
        ...

    @abstractmethod
    def delete_instance(self, instance_id: str) -> None:
        """Tear down. Must be a no-op if already gone (idempotent)."""

    @abstractmethod
    def network_attach(self, instance_id: str, cluster: str) -> dict:
        """Attach to VPC/subnet/routes; the seam for Interconnect/Transit GW/BGP.

        Returns a connectivity descriptor (recorded for observability).
        """

    @abstractmethod
    def apply_security_baseline(self, instance_id: str) -> dict:
        """Apply least-privilege IAM/role + host hardening at the infra layer.

        Returns the baseline descriptor the security policy then validates.
        """
