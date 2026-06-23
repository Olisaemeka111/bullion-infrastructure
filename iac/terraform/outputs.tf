###############################################################################
# Outputs: cluster identifiers + the exact kubeconfig command for each cloud.
# After `terraform apply`, run the printed command to get kubectl access, then:
#   kubectl get nodes -o wide      # expect `node_count` Ready medium nodes
###############################################################################

output "eks" {
  description = "EKS cluster details + kubeconfig command."
  value = var.enable_aws ? {
    cluster_name = module.eks[0].cluster_name
    region       = var.aws_region
    endpoint     = module.eks[0].cluster_endpoint
    kubeconfig   = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks[0].cluster_name}"
  } : null
}

output "gke" {
  description = "GKE Autopilot cluster details + kubeconfig command."
  value = var.enable_gcp ? {
    cluster_name = module.gke[0].cluster_name
    mode         = "standard"
    location     = var.gcp_zone
    endpoint     = module.gke[0].cluster_endpoint
    kubeconfig   = "gcloud container clusters get-credentials ${module.gke[0].cluster_name} --zone ${var.gcp_zone} --project ${var.gcp_project}"
  } : null
  sensitive = true
}

# Re-enable with the aks module (main.tf) when Azure is added.
# output "aks" {
#   description = "AKS cluster details + kubeconfig command."
#   value = var.enable_azure ? {
#     cluster_name        = module.aks[0].cluster_name
#     resource_group_name = module.aks[0].resource_group_name
#     kubeconfig          = "az aks get-credentials --resource-group ${module.aks[0].resource_group_name} --name ${module.aks[0].cluster_name}"
#   } : null
# }
