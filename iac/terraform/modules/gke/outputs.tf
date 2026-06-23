output "cluster_name" {
  value = google_container_cluster.primary.name
}

output "cluster_endpoint" {
  value     = google_container_cluster.primary.endpoint
  sensitive = true
}

output "network" {
  value = google_compute_network.vpc.name
}

output "network_id" {
  value = google_compute_network.vpc.id
}

output "subnet_cidr" {
  value = var.subnet_cidr
}

output "pods_cidr" {
  value = var.pods_cidr
}

output "services_cidr" {
  value = var.services_cidr
}
