# CICD.md — deploy the 3-cloud fleet with GitHub Actions

The pipeline ([.github/workflows/deploy.yml](.github/workflows/deploy.yml)) runs:

| Trigger | Job | Result |
|---|---|---|
| PR touching `iac/terraform/**` | `plan` | `terraform plan` posted as a PR comment |
| merge to `main` | `apply` | `terraform apply` (gated by the `production` environment) |
| **Actions → Run workflow → action=destroy** | `destroy` | `terraform destroy` |

Auth is **keyless (OIDC)** to all three clouds — no static cloud keys in GitHub.
There is a one-time setup below (do it once; then it's just PRs).

---

## 0. Prerequisites (one-time)
You need admin on the GitHub repo and on each cloud account you enable. Replace
`OWNER/REPO` with your repository throughout.

**Secrets are managed in HashiCorp Vault** (see [VAULT.md](VAULT.md)). Set that up
first: `iac/vault/setup.sh` enables GitHub OIDC on Vault and seeds
`secret/cluster-infra-mini/cloud`. The cloud identifiers produced in §2 below go
*into Vault*, and GitHub only needs the `VAULT_ADDR` variable (§3).

---

## 1. Remote state (S3 with native locking — no DynamoDB)
CI runners are ephemeral, so state must live remotely. We use **S3 native state
locking** (`use_lockfile`, Terraform ≥ 1.10), so the lock is just an object in the
same bucket — **no DynamoDB table to create or pay for**. Create the bucket once:

```bash
REGION=us-east-1
BUCKET=fleet-mini-tfstate-$(openssl rand -hex 4)   # must be globally unique
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
echo "TF_STATE_BUCKET=$BUCKET"   # -> GitHub variable
```

---

## 2. Keyless cloud auth (OIDC)

### 2a. AWS
```bash
# OIDC provider for GitHub (once per account)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# Role GitHub assumes (trust limited to your repo); attach a policy that can
# create EKS+VPC+IAM (AdministratorAccess for a test; scope down for prod).
```
Create a role `fleet-mini-gha` with this trust policy, then attach permissions:
```json
{ "Version": "2012-10-17", "Statement": [{
  "Effect": "Allow",
  "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
    "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:*" }
  }}]}
```
→ Vault key `AWS_ROLE_ARN = arn:aws:iam::<ACCOUNT_ID>:role/fleet-mini-gha`
  (store in `secret/cluster-infra-mini/cloud` — see [VAULT.md](VAULT.md))

### 2b. GCP (Workload Identity Federation)
```bash
PROJECT=<your-project>; POOL=github-pool; PROV=github-provider
SA=fleet-mini-gha@$PROJECT.iam.gserviceaccount.com

gcloud iam service-accounts create fleet-mini-gha --project "$PROJECT"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/container.admin
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/compute.admin
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/iam.serviceAccountUser

gcloud iam workload-identity-pools create "$POOL" --project "$PROJECT" --location global
gcloud iam workload-identity-pools providers create-oidc "$PROV" \
  --project "$PROJECT" --location global --workload-identity-pool "$POOL" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository=='OWNER/REPO'"
# allow the repo to impersonate the SA
PROJNUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJNUM/locations/global/workloadIdentityPools/$POOL/attribute.repository/OWNER/REPO"
gcloud services enable container.googleapis.com compute.googleapis.com --project "$PROJECT"
```
→ Vault keys (in `secret/cluster-infra-mini/cloud`):
  `GCP_WIF_PROVIDER = projects/$PROJNUM/locations/global/workloadIdentityPools/github-pool/providers/github-provider`,
  `GCP_SERVICE_ACCOUNT = $SA`, `GCP_PROJECT = $PROJECT`

### 2c. Azure (federated credential)
```bash
APP=$(az ad app create --display-name fleet-mini-gha --query appId -o tsv)
az ad sp create --id "$APP"
SUB=$(az account show --query id -o tsv)
az role assignment create --assignee "$APP" --role Contributor --scope "/subscriptions/$SUB"
# federate the repo's main branch + PRs
az ad app federated-credential create --id "$APP" --parameters '{
  "name":"gh-main","issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:OWNER/REPO:ref:refs/heads/main","audiences":["api://AzureADTokenExchange"]}'
az ad app federated-credential create --id "$APP" --parameters '{
  "name":"gh-pr","issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:OWNER/REPO:pull_request","audiences":["api://AzureADTokenExchange"]}'
echo "AZURE_CLIENT_ID=$APP  AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)  AZURE_SUBSCRIPTION_ID=$SUB"
```
→ Vault keys `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
  (in `secret/cluster-infra-mini/cloud`)

---

## 3. GitHub repo configuration

Secrets live in **Vault**, not GitHub — load the cloud identifiers from steps 2a–2c
into `secret/cluster-infra-mini/cloud` via [VAULT.md](VAULT.md) / `iac/vault/setup.sh`.

**Settings → Secrets and variables → Actions → Secrets:** *(none — no cloud secrets
in GitHub)*

**…→ Variables:**

| Variable | Example | Notes |
|---|---|---|
| `VAULT_ADDR` | `https://<cluster>.vault.<...>.hashicorp.cloud:8200` | the pipeline pulls secrets from here |
| `VAULT_NAMESPACE` | `admin` | HCP Vault namespace |
| `TF_STATE_BUCKET` | `fleet-mini-tfstate-ab12cd34` | step 1 |
| `TF_BACKEND_REGION` | `us-east-1` | bucket region |
| `AWS_REGION` | `us-east-1` | optional (defaults us-east-1) |
| `ENABLE_AWS` / `ENABLE_GCP` / `ENABLE_AZURE` | `true` / `false` | **deploy one cloud first by setting the others false** |

**Settings → Environments → New environment → `production`:** add yourself as a
**required reviewer**. Now every `apply`/`destroy` waits for your click — the
approval gate.

---

## 4. Run it

1. **Plan:** open a PR that touches `iac/terraform/**` (or run the workflow with
   `action=plan`). The plan is posted as a PR comment.
2. **Apply:** merge the PR to `main` → the `apply` job starts and **pauses for
   approval** (production environment) → approve → clusters provision.
3. **Get access** (locally, after apply): use the kubeconfig commands from
   `terraform output` (see [DEPLOY.md](DEPLOY.md) §4), then install the active-active
   mesh ([mesh/README.md](mesh/README.md)).
4. **Destroy:** Actions → **deploy** → **Run workflow** → `action=destroy` → approve.

> **Start with one cloud:** set `ENABLE_GCP=false` and `ENABLE_AZURE=false`, get
> the AWS path green end-to-end, then flip them on — same pipeline, no code change.

---

## 5. Notes
- **Scope the cloud roles down for production.** The examples grant broad admin to
  get you running; least-privilege policies are the hardening step.
- **The mesh + CockroachDB layers are deployed after the clusters exist** (they
  need kubeconfig/ingress hostnames). Keep them as a follow-on `kubectl`/`helm`
  step or a second workflow; they are intentionally not in the cluster-provisioning
  plan/apply.
- The separate [`ci.yml`](.github/workflows/ci.yml) keeps running the 80 Python
  tests + `terraform fmt/validate` on every push with **no** cloud credentials.
