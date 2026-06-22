# VAULT.md — secret management with HashiCorp Vault

Vault is the single source of truth for secrets. Nothing sensitive is stored in
GitHub or committed to git. Two consumers pull from it, both **keyless**:

| Consumer | What it pulls | How it auths |
|---|---|---|
| GitHub Actions (CI/CD) | cloud deploy identifiers (`.../cloud`) | **GitHub OIDC** → Vault JWT auth (`hashicorp/vault-action`) |
| Kubernetes clusters (runtime) | app secrets (`.../app/*`: CockroachDB, Grafana) | **Vault Kubernetes auth** → External Secrets Operator |

GitHub ends up storing only the **public** `VAULT_ADDR` — zero project secrets.

> Cloud auth stays keyless OIDC. Vault holds the *identifiers* (role ARN, WIF
> provider, Azure app id) + the genuine app secrets — it does not hold cloud keys,
> because there are none.

---

## Secret layout (KV v2 at `secret/`)

```
secret/cluster-infra-mini/cloud              # CI/deploy identifiers (read by GitHub Actions)
  AWS_ROLE_ARN, GCP_WIF_PROVIDER, GCP_SERVICE_ACCOUNT, GCP_PROJECT,
  AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID
secret/cluster-infra-mini/app/cockroachdb    # runtime (read by ESO in-cluster)
  username, password
secret/cluster-infra-mini/app/grafana
  admin-user, admin-password
```

Policies (least-privilege, in `iac/vault/policies/`):
- `github-actions-read` → read `secret/data/cluster-infra-mini/cloud` only.
- `eso-read` → read `secret/data/cluster-infra-mini/app/*` only.

---

## 1. One-time configuration

Log in to your HCP Vault as an admin once, then run the setup script:
```bash
export VAULT_ADDR="https://<cluster>.vault.<...>.hashicorp.cloud:8200"
export VAULT_NAMESPACE="admin"
export VAULT_TOKEN="<admin token>"
export GITHUB_REPO="ORG/REPO"

./iac/vault/setup.sh
```
This enables KV v2, writes the two policies, enables + configures GitHub OIDC
(JWT) auth, creates the repo-bound `github-actions` role, and seeds the secret
paths. **Edit the seeded values** with your real identifiers:
```bash
vault kv put secret/cluster-infra-mini/cloud \
  AWS_ROLE_ARN="arn:aws:iam::123456789012:role/fleet-mini-gha" \
  GCP_WIF_PROVIDER="projects/.../providers/github-provider" \
  GCP_SERVICE_ACCOUNT="fleet-mini-gha@my-proj.iam.gserviceaccount.com" \
  GCP_PROJECT="my-proj" \
  AZURE_CLIENT_ID="..." AZURE_TENANT_ID="..." AZURE_SUBSCRIPTION_ID="..."
```
(Get these identifiers from CICD.md §2 — the OIDC setup for each cloud.)

---

## 2. GitHub side (almost nothing)

**Settings → Secrets and variables → Actions → Variables:**

| Variable | Example |
|---|---|
| `VAULT_ADDR` | `https://<cluster>.vault.<...>.hashicorp.cloud:8200` |
| `VAULT_NAMESPACE` | `admin` |

No cloud secrets in GitHub. The pipeline ([deploy.yml](.github/workflows/deploy.yml))
authenticates to Vault with the workflow's OIDC token and pulls the identifiers:

```yaml
- uses: hashicorp/vault-action@v3
  with:
    url: ${{ vars.VAULT_ADDR }}
    namespace: ${{ vars.VAULT_NAMESPACE }}
    method: jwt
    role: github-actions
    jwtGithubAudience: https://github.com/${{ github.repository_owner }}
    secrets: |
      secret/data/cluster-infra-mini/cloud AWS_ROLE_ARN | AWS_ROLE_ARN ;
      ...
```
The pulled values are then used by the cloud OIDC login steps and Terraform.

> **Audience note:** the role's `bound_audiences` (set by `setup.sh` to
> `https://github.com/<owner>`) must match `jwtGithubAudience` in the workflow.
> Both use the repository owner URL, so they line up automatically.

---

## 3. Kubernetes side (runtime app secrets)

For secrets that live *inside* the clusters (CockroachDB, Grafana), use the
**External Secrets Operator** instead of CI:

```bash
# per cluster
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace
```
Enable Vault Kubernetes auth for each cluster and bind it to `eso-read`:
```bash
vault auth enable kubernetes
vault write auth/kubernetes/config kubernetes_host="https://<cluster-api>"
vault write auth/kubernetes/role/eso-read \
  bound_service_account_names="external-secrets" \
  bound_service_account_namespaces="external-secrets" \
  policies="eso-read" ttl="1h"
```
Then apply [mesh/secrets/external-secrets.yaml](mesh/secrets/external-secrets.yaml)
(set the Vault server URL). ESO syncs `secret/cluster-infra-mini/app/*` into native
Kubernetes Secrets (`cockroachdb-creds`, `grafana-admin`) that the workloads mount.

---

## 4. Rotation
- **App secrets:** `vault kv put secret/cluster-infra-mini/app/...`; ESO re-syncs
  on its `refreshInterval` (1h) — no redeploy.
- **CI identifiers:** `vault kv put secret/cluster-infra-mini/cloud ...`; the next
  pipeline run picks them up. Vault tokens issued to CI are short-lived (15m TTL).

---

## 5. Why this is the gold standard
- **No static secrets anywhere** — GitHub uses OIDC to Vault; clusters use K8s auth
  to Vault; clouds use OIDC. Every credential is short-lived.
- **Least privilege** — CI can read only `cloud`; ESO can read only `app/*`.
- **Central rotation + audit** — one place to rotate, and Vault audit logs every read.
