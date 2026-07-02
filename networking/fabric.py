"""Declarative network fabric model.

The control plane plans a `ClusterFabric` per cluster and a `CrossCloudMesh`
across clusters. Providers consume the per-cluster fabric when attaching a node
(see `Provider.network_attach`). The model is intentionally provider-neutral; the
provider maps each field to its concrete primitive (VPC vs VNet, Transit Gateway
vs Network Connectivity Center vs vWAN, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class HostNetwork:
    """Cluster/host (data-plane) networking applied on every node."""
    cni: str = "cilium"                 # eBPF dataplane
    ebpf_dataplane: bool = True
    default_deny: bool = True           # NetworkPolicy posture
    network_policy: str = "default-deny+explicit-allow"
    multi_nic: bool = False             # GPU hosts: separate RDMA/storage NICs
    nics: list[str] = field(default_factory=lambda: ["eth0"])
    sflow: bool = True                  # flow export for failure detection
    service_mesh: str = "envoy"         # istio | envoy | linkerd
    mtls: str = "strict"                # mesh-wide mutual TLS


@dataclass
class EdgeProtection:
    """Edge load balancing + DDoS mitigation in front of public endpoints."""
    edge_lb: str = "global-l7"
    ddos_mitigation: str = "auto"       # cloud-armor (gcp) / aws-shield-adv / azure-ddos
    waf: bool = True


@dataclass
class ClusterFabric:
    """Per-cluster cloud (control/under-lay) networking."""
    cluster: str
    provider: str
    cidr: str = "10.0.0.0/16"
    subnets: list[str] = field(default_factory=lambda: [
        "10.0.0.0/18", "10.0.64.0/18", "10.0.128.0/18"])  # multi-AZ
    shared_vpc: bool = True             # host-project / hub VPC model
    hub_attachment: str = "transit-gateway"   # tgw | ncc | vwan
    interconnect: str = "dedicated"     # interconnect / direct-connect / expressroute
    cloud_nat: bool = True              # egress without public IPs on nodes
    bgp_asn: int = 64512
    route_control: str = "bgp+explicit-routes"
    host: HostNetwork = field(default_factory=HostNetwork)
    edge: EdgeProtection = field(default_factory=EdgeProtection)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PrivateLink:
    a: str               # cluster A
    b: str               # cluster B
    transport: str       # interconnect | direct-connect | expressroute | partner
    bandwidth_gbps: int = 100
    encrypted: bool = True       # private + encrypted (no traversal of public net)


@dataclass
class CrossCloudMesh:
    """Cross-cloud private connectivity between clusters/providers.

    Models the high-bandwidth, secure inter-cluster links the role requires:
    private (no public traversal), BGP-routed, encrypted, hub-and-spoke.
    """
    links: list[PrivateLink] = field(default_factory=list)

    def connect(self, a: str, b: str, transport: str = "interconnect",
                bandwidth_gbps: int = 100) -> PrivateLink:
        link = PrivateLink(a=a, b=b, transport=transport,
                           bandwidth_gbps=bandwidth_gbps)
        self.links.append(link)
        return link

    def to_dict(self) -> dict:
        return {"links": [asdict(link) for link in self.links]}


# Sensible per-provider defaults for the fabric (maps neutral model -> primitives)
PROVIDER_FABRIC_DEFAULTS = {
    "aws": {"hub_attachment": "transit-gateway", "interconnect": "direct-connect",
            "edge_ddos": "aws-shield-advanced"},
    "gcp": {"hub_attachment": "network-connectivity-center",
            "interconnect": "dedicated-interconnect", "edge_ddos": "cloud-armor"},
    "azure": {"hub_attachment": "virtual-wan", "interconnect": "expressroute",
              "edge_ddos": "azure-ddos-protection"},
    "baremetal": {"hub_attachment": "spine-leaf-fabric", "interconnect": "dark-fiber",
                  "edge_ddos": "scrubbing-center"},
}


def build_fabric(cluster: str, provider: str, gpu: bool = True) -> ClusterFabric:
    fab = ClusterFabric(cluster=cluster, provider=provider)
    d = PROVIDER_FABRIC_DEFAULTS.get(provider, {})
    fab.hub_attachment = d.get("hub_attachment", fab.hub_attachment)
    fab.interconnect = d.get("interconnect", fab.interconnect)
    fab.edge.ddos_mitigation = d.get("edge_ddos", fab.edge.ddos_mitigation)
    if gpu:
        # GPU training hosts: dedicated RDMA + storage NICs alongside the pod NIC
        fab.host.multi_nic = True
        fab.host.nics = ["eth0-pod", "eth1-rdma", "eth2-storage"]
    return fab
