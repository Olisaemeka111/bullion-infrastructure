variable "cluster_name" {
  type = string
}

variable "location" {
  type = string
}

variable "kubernetes_version" {
  type = string
}

variable "node_count" {
  type = number
}

variable "node_vm_size" {
  type = string
}

variable "vnet_cidr" {
  type    = string
  default = "10.30.0.0/16"
}

variable "node_subnet_cidr" {
  type    = string
  default = "10.30.0.0/20"
}

variable "service_cidr" {
  type    = string
  default = "10.31.0.0/16"
}

variable "dns_service_ip" {
  type    = string
  default = "10.31.0.10"
}

variable "tags" {
  type    = map(string)
  default = {}
}
