"""Azure backend — managed Kubernetes (Azure AKS).

Mini deployment: an AKS cluster with a default node pool of 2 medium nodes
(Standard_D2s_v3). Real impl: AKS node pools, VNet + Azure CNI + Calico network
policy, system-assigned managed identity. The actual cloud resources are in
`iac/terraform/modules/aks`."""
from ._simbase import SimProvider


class AzureProvider(SimProvider):
    name = "azure"
    network_primitive = "vnet+aks-node-pool"
    iam_model = "managed-identity"
