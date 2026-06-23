###############################################################################
# Root: composes one managed Kubernetes cluster per enabled cloud, each with a
# node pool of `node_count` (default 2) medium nodes. This is the real, deployable
# mirror of the declarative `fleet-mini` spec the control plane reconciles offline
# (see sim/multicloud.py). Networking is provisioned per cloud inside each module.
###############################################################################

provider "aws" {
  region = var.aws_region
}

provider "google" {
  project = var.gcp_project
  region  = var.gcp_region
}

# Azure disabled until a subscription exists. The azurerm provider authenticates
# at plan time even when its module is count=0, so it must stay commented out
# (not just toggled off) to avoid breaking AWS+GCP. Re-enable with the aks module
# below + the AZURE_* GitHub secrets.
# provider "azurerm" {
#   features {}
# }

# ---- AWS : Amazon EKS -------------------------------------------------------
module "eks" {
  source = "./modules/eks"
  count  = var.enable_aws ? 1 : 0

  cluster_name       = "${var.name_prefix}-eks"
  kubernetes_version = var.kubernetes_version
  node_count         = var.node_count
  node_instance_type = var.aws_node_instance_type
  tags               = var.tags
}

# ---- GCP : Google GKE (Autopilot) ------------------------------------------
# Autopilot manages the node fleet automatically (no node_count / machine type).
module "gke" {
  source = "./modules/gke"
  count  = var.enable_gcp ? 1 : 0

  cluster_name = "${var.name_prefix}-gke"
  project      = var.gcp_project
  region       = var.gcp_region
  labels       = var.tags
}

# ---- Azure : Azure AKS ------------------------------------------------------
# Re-enable together with the azurerm provider above once you have an Azure
# subscription + the AZURE_* GitHub secrets, then set ENABLE_AZURE=true.
# module "aks" {
#   source = "./modules/aks"
#   count  = var.enable_azure ? 1 : 0
#
#   cluster_name       = "${var.name_prefix}-aks"
#   location           = var.azure_location
#   kubernetes_version = var.kubernetes_version
#   node_count         = var.node_count
#   node_vm_size       = var.azure_node_vm_size
#   tags               = var.tags
# }
