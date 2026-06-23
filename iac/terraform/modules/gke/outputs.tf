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
