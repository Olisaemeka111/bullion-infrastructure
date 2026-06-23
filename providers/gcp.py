"""GCP backend — managed Kubernetes (Google GKE Standard).

Mini deployment: a zonal GKE Standard cluster with a node pool of 2 medium nodes
(e2-medium). Standard mode (not Autopilot) gives node-level control needed for
self-managed Istio, the node-exporter DaemonSet, and self-hosted CockroachDB.
VPC-native networking with a dedicated VPC + subnet. The actual cloud resources
are in `iac/terraform/modules/gke`."""
from ._simbase import SimProvider


class GCPProvider(SimProvider):
    name = "gcp"
    network_primitive = "vpc-native+gke-node-pool"
    iam_model = "workload-identity"
