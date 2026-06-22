# Remote state — required for CI/CD (ephemeral runners can't share local state).
# Uses S3 NATIVE state locking (use_lockfile = true, Terraform >= 1.10): the lock
# is an object in the same bucket, so there is NO DynamoDB table to create or pay
# for. bucket/key/region are supplied at `init` time via -backend-config so the
# same code works in the pipeline and locally.
#
#   CI:    terraform init -backend-config="bucket=..." -backend-config="key=..." ...
#          (see .github/workflows/deploy.yml + CICD.md)
#   local: terraform init -backend-config=backend.hcl     (your own backend.hcl)
#          or, for validate only: terraform init -backend=false
terraform {
  backend "s3" {
    use_lockfile = true
  }
}
