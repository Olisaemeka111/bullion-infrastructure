"""Unit: secure-by-default gate, admission (PSS), RBAC, hardening."""
import unittest

from control_plane.models import Node, NodeState
from security import policy
from security.admission import admit, WorkloadSpec
from security.rbac import authorize, ROLES
from security.hardening import verify, CIS_BASELINE_V1


def healthy_node(image="sha256:GOLD", attested=True):
    n = Node(pool="p", cluster="c", provider="aws", instance_type="t")
    n.image_digest = image
    n.attested = attested
    return n


GOOD_BASELINE = {"least_privilege": True, "host_hardening": "cis-baseline-v1"}


class TestPolicyGate(unittest.TestCase):
    def test_compliant_node_passes(self):
        r = policy.evaluate(healthy_node(), GOOD_BASELINE, "sha256:GOLD")
        self.assertTrue(r.passed, r.failures)

    def test_unverified_image_fails(self):
        r = policy.evaluate(healthy_node(image="sha256:EVIL"), GOOD_BASELINE, "sha256:GOLD")
        self.assertFalse(r.passed)
        self.assertTrue(any("provenance" in f for f in r.failures))

    def test_unattested_fails(self):
        r = policy.evaluate(healthy_node(attested=False), GOOD_BASELINE, "sha256:GOLD")
        self.assertFalse(r.passed)

    def test_missing_hardening_fails(self):
        r = policy.evaluate(healthy_node(), {"least_privilege": True}, "sha256:GOLD")
        self.assertFalse(r.passed)

    def test_overprivileged_fails(self):
        r = policy.evaluate(healthy_node(),
                            {"least_privilege": False, "host_hardening": "cis-baseline-v1"},
                            "sha256:GOLD")
        self.assertFalse(r.passed)


class TestAdmission(unittest.TestCase):
    def test_restricted_blocks_unsigned_untrusted(self):
        r = admit(WorkloadSpec("x", "docker.io/evil", image_signed=False))
        self.assertFalse(r.allowed)
        self.assertTrue(any("not signed" in v for v in r.violations))
        self.assertTrue(any("trusted registry" in v for v in r.violations))

    def test_restricted_blocks_privileged_root_hostnet(self):
        r = admit(WorkloadSpec("x", "registry.internal/app", image_signed=True,
                               privileged=True, run_as_root=True, host_network=True))
        self.assertFalse(r.allowed)
        self.assertGreaterEqual(len(r.violations), 3)

    def test_compliant_signed_workload_allowed(self):
        r = admit(WorkloadSpec("trainer", "registry.internal/trainer:abc",
                               image_signed=True))
        self.assertTrue(r.allowed, r.violations)

    def test_baseline_more_permissive_than_restricted(self):
        spec = WorkloadSpec("x", "registry.internal/app", image_signed=True,
                            run_as_root=True)  # root ok under baseline, not restricted
        self.assertTrue(admit(spec, pss_level="baseline").allowed)
        self.assertFalse(admit(spec, pss_level="restricted").allowed)


class TestRBAC(unittest.TestCase):
    def test_automation_can_drain_not_read_secrets(self):
        self.assertTrue(authorize("control-plane-automation", "drain", "nodes"))
        self.assertFalse(authorize("control-plane-automation", "get", "secrets"))

    def test_viewer_is_read_only(self):
        self.assertTrue(authorize("viewer", "get", "nodes"))
        self.assertFalse(authorize("viewer", "delete", "nodes"))

    def test_no_role_is_implicit_admin(self):
        # only break-glass has wildcard
        wildcards = [n for n, r in ROLES.items() if "*" in r.verbs]
        self.assertEqual(wildcards, ["break-glass"])

    def test_unknown_role_denied(self):
        self.assertFalse(authorize("does-not-exist", "get", "nodes"))


class TestHardening(unittest.TestCase):
    def test_verify_matches_golden(self):
        self.assertTrue(verify("cis-baseline-v1"))
        self.assertFalse(verify("cis-baseline-v0"))

    def test_baseline_covers_node_runtime_kubelet(self):
        for k in ("node", "container_runtime", "kubelet"):
            self.assertIn(k, CIS_BASELINE_V1)
            self.assertTrue(CIS_BASELINE_V1[k])


if __name__ == "__main__":
    unittest.main()
