# Least-privilege policy for the External Secrets Operator running in each cluster.
# It may READ only the in-cluster application secrets (CockroachDB, Grafana, ...),
# never the CI/deploy identifiers.
path "secret/data/cluster-infra-mini/app/*" {
  capabilities = ["read"]
}
path "secret/metadata/cluster-infra-mini/app/*" {
  capabilities = ["read"]
}
