###############################################################################
# GCP — Google GKE Standard (zonal, so node_count is the exact total node count)
# with a separately-managed node pool of `node_count` medium nodes. Standard mode
# (not Autopilot) gives node-level control needed for self-managed Istio, the
# node-exporter DaemonSet, and self-hosted CockroachDB.
# Networking: dedicated VPC-native network + subnet with secondary ranges.
###############################################################################

resource "google_compute_network" "vpc" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "${var.cluster_name}-subnet"
  region        = var.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = var.subnet_cidr

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }
}

resource "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.zone # zonal => node_count nodes total (not per-zone)

  remove_default_node_pool = true
  initial_node_count       = 1

  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.subnet.id

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  release_channel {
    channel = "REGULAR"
  }

  # Required for the node pool's GKE_METADATA (Workload Identity) setting.
  workload_identity_config {
    workload_pool = "${var.project}.svc.id.goog"
  }

  deletion_protection = false
}

resource "google_container_node_pool" "primary" {
  name       = "default"
  location   = var.zone
  cluster    = google_container_cluster.primary.name
  node_count = var.node_count

  node_config {
    machine_type = var.node_machine_type
    disk_size_gb = 50
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    labels       = var.labels

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}
