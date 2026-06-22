# Least-privilege policy for the GitHub Actions deploy pipeline.
# It may READ only the project's CI/deploy identifiers — nothing else in Vault.
path "secret/data/cluster-infra-mini/cloud" {
  capabilities = ["read"]
}
path "secret/metadata/cluster-infra-mini/cloud" {
  capabilities = ["read"]
}
