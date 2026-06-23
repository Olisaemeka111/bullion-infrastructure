###############################################################################
# Mini multi-cloud managed-Kubernetes fleet — 2 medium nodes per cloud.
# Toggle each cloud independently so you can test one at a time (and limit cost).
###############################################################################

variable "name_prefix" {
  description = "Prefix applied to all cluster / network names (e.g. bullion-eks, bullion-gke)."
  type        = string
  default     = "bullion"
}

variable "node_count" {
  description = "Worker nodes per managed cluster (the 'mini' size)."
  type        = number
  default     = 2
}

variable "kubernetes_version" {
  description = "Kubernetes minor version for EKS (must be a currently-supported EKS version). GKE Autopilot ignores this and uses its release channel."
  type        = string
  default     = "1.32"
}

variable "tags" {
  description = "Common tags / labels applied to resources."
  type        = map(string)
  default = {
    project   = "cluster-infra-mini"
    managedby = "terraform"
    env       = "test"
  }
}

# ---- per-cloud enable switches ---------------------------------------------
variable "enable_aws" {
  type    = bool
  default = true
}
variable "enable_gcp" {
  type    = bool
  default = true
}
variable "enable_azure" {
  type    = bool
  default = true
}
variable "enable_cross_cloud" {
  description = "Build the AWS<->GCP HA VPN (cross-cloud peering) for the central database fabric."
  type        = bool
  default     = false
}

# ---- AWS (EKS) --------------------------------------------------------------
variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "aws_node_instance_type" {
  description = "Medium EKS managed node group instance type."
  type        = string
  default     = "t3.medium"
}

# ---- GCP (GKE Autopilot) ----------------------------------------------------
# Autopilot is regional and manages nodes itself, so there is no zone, node
# count or machine type to configure for GKE.
variable "gcp_project" {
  description = "GCP project id (required when enable_gcp = true)."
  type        = string
  default     = ""
}
variable "gcp_region" {
  type    = string
  default = "us-central1"
}
variable "gcp_zone" {
  description = "Zone for the zonal GKE Standard cluster (exact total node count)."
  type        = string
  default     = "us-central1-a"
}
variable "gcp_node_machine_type" {
  description = "Medium GKE node machine type."
  type        = string
  default     = "e2-medium"
}

# ---- Azure (AKS) ------------------------------------------------------------
variable "azure_location" {
  type    = string
  default = "eastus"
}
variable "azure_node_vm_size" {
  description = "Medium AKS node VM size."
  type        = string
  default     = "Standard_D2s_v3"
}
