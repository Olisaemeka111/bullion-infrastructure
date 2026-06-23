output "aws_vpn_gateway_id" {
  value = aws_vpn_gateway.aws.id
}

output "gcp_ha_vpn_gateway" {
  value = google_compute_ha_vpn_gateway.gcp.name
}

output "note" {
  value = "AWS<->GCP HA VPN: 4 BGP tunnels. After apply, confirm all tunnels are UP (AWS console / 'gcloud compute vpn-tunnels list') before relying on cross-cloud routing for CockroachDB."
}
