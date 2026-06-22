"""Cloud + host networking model for the fleet.

Covers the two layers the role calls out:
- Cloud networking: VPC design/peering, Shared VPC / Transit Gateway,
  Interconnect/Direct Connect/ExpressRoute, Cloud NAT, cross-cloud private
  connectivity, BGP/route control, edge load balancing + DDoS mitigation.
- Cluster/host networking: Cilium (eBPF) CNI, NetworkPolicy (default-deny),
  multi-NIC, sFlow, service mesh + mTLS.
"""
