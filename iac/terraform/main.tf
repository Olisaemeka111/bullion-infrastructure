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

# ---- GCP : Google GKE (Standard) -------------------------------------------
module "gke" {
  source = "./modules/gke"
  count  = var.enable_gcp ? 1 : 0

  cluster_name      = "${var.name_prefix}-gke"
  project           = var.gcp_project
  region            = var.gcp_region
  zone              = var.gcp_zone
  node_count        = var.node_count
  node_machine_type = var.gcp_node_machine_type
  labels            = var.tags
}

# ---- Cross-cloud private connectivity (AWS <-> GCP HA VPN + BGP) ------------
# The private substrate that joins the two clouds into one fabric (needed for the
# central CockroachDB). Requires both AWS + GCP enabled. Off by default.
module "cross_cloud" {
  source = "./modules/cross_cloud"
  count  = (var.enable_aws && var.enable_gcp && var.enable_cross_cloud) ? 1 : 0

  name_prefix         = "${var.name_prefix}-xc"
  aws_vpc_id          = module.eks[0].vpc_id
  aws_route_table_ids = module.eks[0].private_route_table_ids
  gcp_network         = module.gke[0].network_id
  gcp_region          = var.gcp_region
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
