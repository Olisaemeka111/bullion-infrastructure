"""RBAC + least-privilege IAM model (as code).

Defines the small set of roles the control plane and operators use. Principle:
least privilege by default — no role gets cluster-admin, destructive verbs are
separated from read/observe verbs, and the automation's own identity can only do
exactly what the lifecycle requires.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Role:
    name: str
    verbs: set[str]
    resources: set[str]
    note: str = ""


# Cluster-scoped roles, deliberately narrow.
ROLES = {
    # The reconciler's own identity: manage node lifecycle, nothing else.
    "control-plane-automation": Role(
        name="control-plane-automation",
        verbs={"get", "list", "watch", "create", "update", "drain", "delete"},
        resources={"nodes", "nodepools", "clusters"},
        note="No access to workloads/secrets; cannot grant roles."),
    # On-call: observe everything, drain a node, but not delete clusters.
    "oncall-operator": Role(
        name="oncall-operator",
        verbs={"get", "list", "watch", "drain", "cordon"},
        resources={"nodes", "clusters", "metrics"},
        note="Destructive cluster ops require break-glass approval."),
    # Read-only for researchers/dashboards.
    "viewer": Role(
        name="viewer",
        verbs={"get", "list", "watch"},
        resources={"nodes", "clusters", "metrics"}),
    # Break-glass: full control, time-boxed, audited, requires approver.
    "break-glass": Role(
        name="break-glass",
        verbs={"*"}, resources={"*"},
        note="Time-boxed + approver required; every use is alerted on."),
}


@dataclass
class Binding:
    principal: str           # user / service-account / spiffe id
    role: str
    approved_by: str = ""    # required for break-glass


def authorize(role_name: str, verb: str, resource: str) -> bool:
    role = ROLES.get(role_name)
    if not role:
        return False
    verb_ok = "*" in role.verbs or verb in role.verbs
    res_ok = "*" in role.resources or resource in role.resources
    return verb_ok and res_ok


# Least-privilege cloud IAM the node instances run with (no broad permissions).
NODE_IAM_PERMISSIONS = {
    "aws": ["ec2:DescribeTags", "ecr:GetAuthorizationToken",
            "s3:GetObject@artifacts-bucket"],
    "gcp": ["logging.write", "monitoring.write", "artifactregistry.read"],
    "azure": ["Microsoft.ContainerRegistry/registries/pull",
              "Microsoft.Storage/blob/read@artifacts"],
}
