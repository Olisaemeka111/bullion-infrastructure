"""Bare-metal / on-prem backend.

Real impl: PXE/iPXE image push, Redfish/IPMI out-of-band power control, a metal
provisioner (Tinkerbell / MAAS / Foreman), BGP route injection for multi-NIC GPU
hosts. The key difference from cloud: power-on and OS image delivery are
out-of-band, and there is no elastic capacity — machines are pre-racked.
"""
from ._simbase import SimProvider


class BareMetalProvider(SimProvider):
    name = "baremetal"
    network_primitive = "bgp+multi-nic"
    iam_model = "spiffe-svid"

    def network_attach(self, instance_id, cluster):
        d = super().network_attach(instance_id, cluster)
        d.update({"bgp": True, "multi_nic": True, "fabric": "rdma"})
        return d
