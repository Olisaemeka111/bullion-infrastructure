"""GCP backend — managed Kubernetes (Google GKE, Autopilot mode).

Mini deployment: a GKE Autopilot cluster — Google fully manages the node fleet
(no node pool / machine type / count); nodes are provisioned automatically from
Pod resource requests. VPC-native networking with a dedicated VPC + subnet and
Dataplane V2 (eBPF). The actual cloud resources are in
`iac/terraform/modules/gke`.

Note: the offline control-plane simulation still models a small pool of nodes for
GCP so the same reconcile/self-heal logic is exercised uniformly across clouds;
in the real GCP deployment that node management is delegated to Autopilot."""
from ._simbase import SimProvider


class GCPProvider(SimProvider):
    name = "gcp"
    network_primitive = "vpc-native+gke-autopilot"
    iam_model = "workload-identity"
