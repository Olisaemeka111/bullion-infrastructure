"""AWS backend — managed Kubernetes (Amazon EKS).

Mini deployment: an EKS cluster with a managed node group of 2 medium nodes
(t3.medium). Real impl: EKS managed node groups + Launch Templates, VPC across
2 AZs + NAT, IAM roles for service accounts (IRSA). The actual cloud resources
are in `iac/terraform/modules/eks`."""
from ._simbase import SimProvider


class AWSProvider(SimProvider):
    name = "aws"
    network_primitive = "vpc+eks-managed-nodegroup"
    iam_model = "irsa"  # IAM roles for service accounts
