variable "cluster_name" {
  type = string
}

variable "kubernetes_version" {
  type = string
}

variable "node_count" {
  type = number
}

variable "node_instance_type" {
  type = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

variable "tags" {
  type    = map(string)
  default = {}
}
