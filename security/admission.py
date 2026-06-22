"""Admission control: Pod Security Standards + supply-chain provenance.

The validating-admission-webhook analog. Every workload admitted to a cluster is
checked against the cluster's Pod Security Standard and against image provenance
(only signed images from trusted registries run). Rejections are hard failures —
there is no path to run an unsigned or over-privileged workload.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Pod Security Standards (Kubernetes): privileged < baseline < restricted
PSS_LEVELS = ("privileged", "baseline", "restricted")
TRUSTED_REGISTRIES = ("registry.internal/", "ghcr.io/anthropic-trusted/")


@dataclass
class WorkloadSpec:
    name: str
    image: str
    image_signed: bool = False
    run_as_root: bool = False
    privileged: bool = False
    host_network: bool = False
    host_path_mounts: list[str] = field(default_factory=list)
    drop_all_caps: bool = True
    read_only_root_fs: bool = True


@dataclass
class AdmissionResult:
    allowed: bool
    violations: list[str] = field(default_factory=list)


def _registry_trusted(image: str) -> bool:
    return any(image.startswith(r) for r in TRUSTED_REGISTRIES)


def admit(spec: WorkloadSpec, pss_level: str = "restricted") -> AdmissionResult:
    v: list[str] = []

    # --- supply-chain / image provenance ---
    if not spec.image_signed:
        v.append(f"image {spec.image} is not signed (cosign verification failed)")
    if not _registry_trusted(spec.image):
        v.append(f"image {spec.image} not from a trusted registry")

    # --- pod security standard enforcement ---
    if pss_level == "restricted":
        if spec.privileged:
            v.append("privileged containers forbidden under 'restricted'")
        if spec.run_as_root:
            v.append("running as root forbidden under 'restricted'")
        if spec.host_network:
            v.append("hostNetwork forbidden under 'restricted'")
        if spec.host_path_mounts:
            v.append(f"hostPath mounts forbidden under 'restricted': {spec.host_path_mounts}")
        if not spec.drop_all_caps:
            v.append("must drop ALL capabilities under 'restricted'")
        if not spec.read_only_root_fs:
            v.append("root filesystem must be read-only under 'restricted'")
    elif pss_level == "baseline":
        if spec.privileged:
            v.append("privileged containers forbidden under 'baseline'")
        if spec.host_network:
            v.append("hostNetwork forbidden under 'baseline'")

    return AdmissionResult(allowed=not v, violations=v)
