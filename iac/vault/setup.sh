#!/usr/bin/env bash
# One-time HCP Vault setup for keyless CI/CD + in-cluster secret management.
# Configures: KV v2, least-privilege policies, GitHub OIDC (JWT) auth, a repo-bound
# role, and seeds the project's secret paths.
#
# Prereqs: vault CLI, and you are logged in to your HCP Vault (admin namespace):
#   export VAULT_ADDR="https://<your-cluster>.vault.<...>.hashicorp.cloud:8200"
#   export VAULT_NAMESPACE="admin"
#   export VAULT_TOKEN="<an admin token>"     # human/admin login, used once
#   export GITHUB_REPO="ORG/REPO"             # your repo
set -euo pipefail

: "${VAULT_ADDR:?set VAULT_ADDR}"
: "${GITHUB_REPO:?set GITHUB_REPO=ORG/REPO}"
export VAULT_NAMESPACE="${VAULT_NAMESPACE:-admin}"
GITHUB_OWNER="${GITHUB_REPO%%/*}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> 1/5 enable KV v2 at secret/"
vault secrets enable -path=secret kv-v2 2>/dev/null || echo "   (already enabled)"

echo "==> 2/5 write least-privilege policies"
vault policy write github-actions-read "$HERE/policies/github-actions-read.hcl"
vault policy write eso-read            "$HERE/policies/eso-read.hcl"

echo "==> 3/5 enable + configure GitHub OIDC (JWT) auth"
vault auth enable jwt 2>/dev/null || echo "   (already enabled)"
vault write auth/jwt/config \
  oidc_discovery_url="https://token.actions.githubusercontent.com" \
  bound_issuer="https://token.actions.githubusercontent.com"

echo "==> 4/5 create the repo-bound role 'github-actions'"
# Bound to the repository (covers PR plans AND main applies). The policy is
# read-only on the CI path, so repo-level binding is safe + least-privilege.
# Audience must match what vault-action sends (https://github.com/<owner>).
vault write auth/jwt/role/github-actions \
  role_type="jwt" \
  user_claim="actor" \
  bound_audiences="https://github.com/${GITHUB_OWNER}" \
  bound_claims_type="glob" \
  bound_claims="{\"repository\":\"${GITHUB_REPO}\"}" \
  token_policies="github-actions-read" \
  token_ttl="15m"

echo "==> 5/5 seed secret paths"
# CI/deploy identifiers (the pipeline pulls these via OIDC). Real values are taken
# from the environment when present (generate-credentials.sh sets them); otherwise
# placeholders are written for you to edit with `vault kv put`.
vault kv put secret/cluster-infra-mini/cloud \
  AWS_ROLE_ARN="${AWS_ROLE_ARN:-arn:aws:iam::<ACCOUNT_ID>:role/fleet-mini-gha}" \
  GCP_WIF_PROVIDER="${GCP_WIF_PROVIDER:-projects/<NUM>/locations/global/workloadIdentityPools/github-pool/providers/github-provider}" \
  GCP_SERVICE_ACCOUNT="${GCP_SERVICE_ACCOUNT:-fleet-mini-gha@<PROJECT>.iam.gserviceaccount.com}" \
  GCP_PROJECT="${GCP_PROJECT:-<PROJECT>}" \
  AZURE_CLIENT_ID="${AZURE_CLIENT_ID:-<APP_ID>}" \
  AZURE_TENANT_ID="${AZURE_TENANT_ID:-<TENANT_ID>}" \
  AZURE_SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-<SUBSCRIPTION_ID>}"

# In-cluster application secrets (pulled by External Secrets Operator, not CI).
# Random passwords are generated here so no secret is ever typed or committed.
vault kv put secret/cluster-infra-mini/app/cockroachdb \
  username="app" password="${CRDB_PASSWORD:-$(openssl rand -base64 24)}"
vault kv put secret/cluster-infra-mini/app/grafana \
  admin-user="admin" admin-password="${GRAFANA_PASSWORD:-$(openssl rand -base64 24)}"

echo "✓ Vault configured. GitHub stores only VAULT_ADDR (no project secrets)."
echo "  Verify:  vault read auth/jwt/role/github-actions"
