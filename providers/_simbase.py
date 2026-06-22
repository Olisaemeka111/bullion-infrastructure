"""Shared simulated backend.

Real providers would call EC2 Fleet / GCE Instance Groups / VMSS / Redfish here.
We simulate an in-memory fleet so the entire lifecycle is runnable and testable
offline. Each subclass only customizes provider-specific descriptors (IAM model,
network primitives) so the differences between clouds and bare metal are explicit
and small.
"""
from __future__ import annotations

import random

from .base import Provider, Instance


class SimProvider(Provider):
    # subclasses override these to reflect real provider primitives
    network_primitive = "vpc"
    iam_model = "generic-role"
    failure_rate = 0.0  # inject provisioning flakiness for self-heal testing

    def __init__(self, failure_rate: float | None = None):
        self._fleet: dict[str, Instance] = {}
        if failure_rate is not None:
            self.failure_rate = failure_rate

    def create_instance(self, node_id, instance_type, region, image_digest):
        # idempotent: keyed by node_id
        if node_id in self._fleet and self._fleet[node_id].status != "gone":
            return self._fleet[node_id]
        if random.random() < self.failure_rate:
            inst = Instance(instance_id=f"{self.name}:{node_id}", status="failed")
            self._fleet[node_id] = inst
            return inst
        inst = Instance(
            instance_id=f"{self.name}:{node_id}",
            status="running",
            private_ip=f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        )
        self._fleet[node_id] = inst
        return inst

    def get_instance(self, instance_id):
        for inst in self._fleet.values():
            if inst.instance_id == instance_id:
                return inst
        return Instance(instance_id=instance_id, status="gone")

    def delete_instance(self, instance_id):
        for inst in self._fleet.values():
            if inst.instance_id == instance_id:
                inst.status = "gone"  # idempotent
        return None

    def network_attach(self, instance_id, cluster):
        # Build the provider-mapped fabric (VPC/peering/TGW/Interconnect/NAT/BGP,
        # plus host networking: Cilium/eBPF/NetworkPolicy/multi-NIC/sFlow/mesh/mTLS).
        from networking.fabric import build_fabric
        fab = build_fabric(cluster, self.name).to_dict()
        fab["instance"] = instance_id
        return fab

    def apply_security_baseline(self, instance_id):
        return {
            "provider": self.name,
            "iam_model": self.iam_model,
            "least_privilege": True,
            "host_hardening": "cis-baseline-v1",
            "instance": instance_id,
        }
