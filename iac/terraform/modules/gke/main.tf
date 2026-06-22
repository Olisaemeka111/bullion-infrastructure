###############################################################################
# GCP — Google GKE in AUTOPILOT mode.
# In Autopilot, Google fully manages the node fleet: there is no node pool,
# machine type or node count to set — nodes are provisioned automatically from
# Pod resource requests and you are billed per Pod resources. This is the
# recommended hands-off managed option.
# Networking: a dedicated VPC-native network + subnet with secondary ranges for
# pods and services (alias IP). Autopilot uses Dataplane V2 (eBPF) by default.
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
  location = var.region # Autopilot clusters are regional

  enable_autopilot = true

  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.subnet.id

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  release_channel {
    channel = "REGULAR" # required for Autopilot; manages the K8s version
  }

  deletion_protection = false
}
