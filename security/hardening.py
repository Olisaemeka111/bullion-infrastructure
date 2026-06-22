"""Node + container hardening baseline (as code).

The concrete controls behind the `cis-baseline-v1` token that
`provider.apply_security_baseline()` reports and `policy.evaluate()` checks. Kept
as data so the baseline is reviewable and versioned.
"""
from __future__ import annotations

CIS_BASELINE_V1 = {
    "node": [
        "disable-root-ssh",
        "ssh-key-only-auth",
        "auditd-enabled",
        "kernel-lockdown-confidentiality",
        "no-unprivileged-bpf",
        "readonly-/boot",
        "automatic-security-updates",
        "host-firewall-default-deny",
    ],
    "container_runtime": [
        "seccomp-default=RuntimeDefault",
        "apparmor-enabled",
        "no-new-privileges",
        "userns-remap",
        "readonly-rootfs-default",
        "drop-all-caps-default",
    ],
    "kubelet": [
        "anonymous-auth=false",
        "authorization-mode=Webhook",
        "rotate-certificates=true",
        "protect-kernel-defaults=true",
        "read-only-port=0",
    ],
}


def verify(reported_baseline: str) -> bool:
    """A node's reported baseline must match the current golden baseline id."""
    return reported_baseline == "cis-baseline-v1"
