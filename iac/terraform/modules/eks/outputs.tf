output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_route_table_ids" {
  value = module.vpc.private_route_table_ids
}

output "vpc_cidr" {
  value = module.vpc.vpc_cidr_block
}

output "node_security_group_id" {
  value = module.eks.node_security_group_id
}
