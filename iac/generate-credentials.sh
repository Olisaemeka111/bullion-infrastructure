#!/usr/bin/env bash
# generate-credentials.sh — create EVERY credential the pipeline needs, in one go,
# and load them into Vault. Run this once from a machine that is logged in to the
# clouds you enable and to Vault.
#
# What it creates:
#   * S3 bucket for Terraform remote state (native locking, no DynamoDB)
#   * AWS  : GitHub OIDC provider + IAM role  (-> AWS_ROLE_ARN)
#   * GCP  : Workload Identity pool/provider + service account (-> GCP_WIF_PROVIDER, SA)
#   * Azure: app registration + federated credentials (-> AZURE_CLIENT_ID/TENANT/SUB)
#   * random app passwords (CockroachDB, Grafana)
#   * writes all of the above into Vault via iac/vault/setup.sh
#
# It does NOT print or commit any secret. Cloud credentials are created in YOUR
# accounts using YOUR logged-in CLIs — they cannot be minted from anywhere else.
#
# Required env:
#   GITHUB_REPO=ORG/REPO   VAULT_ADDR=https://...:8200   [VAULT_NAMESPACE=admin]
#   GCP_PROJECT=<id>       (only if you enable GCP)
# Toggle clouds: ENABLE_AWS / ENABLE_GCP / ENABLE_AZURE  (default true)
set -euo pipefail

: "${GITHUB_REPO:?set GITHUB_REPO=ORG/REPO}"
: "${VAULT_ADDR:?set VAULT_ADDR}"
export VAULT_NAMESPACE="${VAULT_NAMESPACE:-admin}"
ENABLE_AWS="${ENABLE_AWS:-true}"; ENABLE_GCP="${ENABLE_GCP:-true}"; ENABLE_AZURE="${ENABLE_AZURE:-true}"
OWNER="${GITHUB_REPO%%/*}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REGION="${AWS_REGION:-us-east-1}"

# ---------------------------------------------------------------- AWS -------
if [[ "$ENABLE_AWS" == "true" ]]; then
  echo "==> AWS: state bucket + GitHub OIDC role"
  ACCT=$(aws sts get-caller-identity --query Account --output text)
  export TF_STATE_BUCKET="${TF_STATE_BUCKET:-fleet-mini-tfstate-$(openssl rand -hex 4)}"
  aws s3api create-bucket --bucket "$TF_STATE_BUCKET" --region "$REGION" \
    $( [[ "$REGION" != "us-east-1" ]] && echo --create-bucket-configuration LocationConstraint="$REGION" ) 2>/dev/null || true
  aws s3api put-bucket-versioning --bucket "$TF_STATE_BUCKET" \
    --versioning-configuration Status=Enabled

  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 2>/dev/null || true

  TRUST=$(mktemp)
  cat > "$TRUST" <<JSON
{ "Version":"2012-10-17","Statement":[{
  "Effect":"Allow",
  "Principal":{"Federated":"arn:aws:iam::${ACCT}:oidc-provider/token.actions.githubusercontent.com"},
  "Action":"sts:AssumeRoleWithWebIdentity",
  "Condition":{
    "StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com"},
    "StringLike":{"token.actions.githubusercontent.com:sub":"repo:${GITHUB_REPO}:*"}}}]}
JSON
  aws iam create-role --role-name fleet-mini-gha \
    --assume-role-policy-document "file://$TRUST" 2>/dev/null || \
    aws iam update-assume-role-policy --role-name fleet-mini-gha --policy-document "file://$TRUST"
  # broad for a test; scope down for prod
  aws iam attach-role-policy --role-name fleet-mini-gha \
    --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
  export AWS_ROLE_ARN="arn:aws:iam::${ACCT}:role/fleet-mini-gha"
  echo "   AWS_ROLE_ARN=$AWS_ROLE_ARN   TF_STATE_BUCKET=$TF_STATE_BUCKET"
fi

# ---------------------------------------------------------------- GCP -------
if [[ "$ENABLE_GCP" == "true" ]]; then
  : "${GCP_PROJECT:?set GCP_PROJECT to enable GCP}"
  echo "==> GCP: Workload Identity Federation + service account"
  SA="fleet-mini-gha@${GCP_PROJECT}.iam.gserviceaccount.com"
  gcloud services enable container.googleapis.com compute.googleapis.com iamcredentials.googleapis.com --project "$GCP_PROJECT"
  gcloud iam service-accounts create fleet-mini-gha --project "$GCP_PROJECT" 2>/dev/null || true
  for role in roles/container.admin roles/compute.admin roles/iam.serviceAccountUser; do
    gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member "serviceAccount:$SA" --role "$role" >/dev/null
  done
  gcloud iam workload-identity-pools create github-pool --project "$GCP_PROJECT" --location global 2>/dev/null || true
  gcloud iam workload-identity-pools providers create-oidc github-provider \
    --project "$GCP_PROJECT" --location global --workload-identity-pool github-pool \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition "assertion.repository=='${GITHUB_REPO}'" 2>/dev/null || true
  PROJNUM=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')
  gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$GCP_PROJECT" \
    --role roles/iam.workloadIdentityUser \
    --member "principalSet://iam.googleapis.com/projects/${PROJNUM}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${GITHUB_REPO}" >/dev/null
  export GCP_WIF_PROVIDER="projects/${PROJNUM}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
  export GCP_SERVICE_ACCOUNT="$SA"
  echo "   GCP_SERVICE_ACCOUNT=$SA"
fi

# -------------------------------------------------------------- Azure ------
if [[ "$ENABLE_AZURE" == "true" ]]; then
  echo "==> Azure: app registration + federated credentials"
  APP=$(az ad app create --display-name fleet-mini-gha --query appId -o tsv)
  az ad sp create --id "$APP" 2>/dev/null || true
  SUB=$(az account show --query id -o tsv)
  TENANT=$(az account show --query tenantId -o tsv)
  az role assignment create --assignee "$APP" --role Contributor --scope "/subscriptions/$SUB" 2>/dev/null || true
  for fc in \
    '{"name":"gh-main","issuer":"https://token.actions.githubusercontent.com","subject":"repo:'"$GITHUB_REPO"':ref:refs/heads/main","audiences":["api://AzureADTokenExchange"]}' \
    '{"name":"gh-pr","issuer":"https://token.actions.githubusercontent.com","subject":"repo:'"$GITHUB_REPO"':pull_request","audiences":["api://AzureADTokenExchange"]}'; do
    az ad app federated-credential create --id "$APP" --parameters "$fc" 2>/dev/null || true
  done
  export AZURE_CLIENT_ID="$APP" AZURE_TENANT_ID="$TENANT" AZURE_SUBSCRIPTION_ID="$SUB"
  echo "   AZURE_CLIENT_ID=$APP"
fi

# --------------------------------------------------- Vault (store it all) ---
echo "==> Vault: scaffold OIDC auth/policies + store all credentials"
# generate-credentials.sh exports AWS_ROLE_ARN/GCP_*/AZURE_* which setup.sh reads.
"$HERE/vault/setup.sh"

echo
echo "✓ Done. Now set these GitHub repo VARIABLES (no secrets):"
echo "   VAULT_ADDR=$VAULT_ADDR"
echo "   VAULT_NAMESPACE=$VAULT_NAMESPACE"
[[ "${TF_STATE_BUCKET:-}" ]] && echo "   TF_STATE_BUCKET=$TF_STATE_BUCKET"
echo "   TF_BACKEND_REGION=$REGION   AWS_REGION=$REGION"
echo "   ENABLE_AWS=$ENABLE_AWS  ENABLE_GCP=$ENABLE_GCP  ENABLE_AZURE=$ENABLE_AZURE"
