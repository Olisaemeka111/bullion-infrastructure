# Cross-cloud private connectivity (AWS <-> GCP) via HA VPN + BGP.
# There is no native AWS<->GCP VPC peering, so this builds redundant IPsec tunnels
# with dynamic (BGP) routing between the EKS VPC and the GKE VPC. This is the
# private substrate the central CockroachDB (and optional pod-to-pod) traffic uses.

variable "name_prefix" {
  type = string
}

# ---- AWS side (EKS VPC) ----
variable "aws_vpc_id" {
  type = string
}
variable "aws_route_table_ids" {
  description = "Private route tables that should learn GCP routes via BGP."
  type        = list(string)
}
variable "aws_amazon_side_asn" {
  type    = number
  default = 64512
}

# ---- GCP side (GKE VPC) ----
variable "gcp_network" {
  description = "GKE VPC network self_link/id."
  type        = string
}
variable "gcp_region" {
  type = string
}
variable "gcp_router_asn" {
  type    = number
  default = 65001
}
