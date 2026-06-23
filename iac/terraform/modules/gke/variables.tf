# GKE Standard: explicit node pool (count + machine type), zonal for an exact
# total node count.

variable "cluster_name" {
  type = string
}

variable "project" {
  type = string
}

variable "region" {
  type = string
}

variable "zone" {
  type = string
}

variable "node_count" {
  type = number
}

variable "node_machine_type" {
  type = string
}

variable "subnet_cidr" {
  type    = string
  default = "10.20.0.0/20"
}

variable "pods_cidr" {
  type    = string
  default = "10.21.0.0/16"
}

variable "services_cidr" {
  type    = string
  default = "10.22.0.0/20"
}

variable "labels" {
  type    = map(string)
  default = {}
}
