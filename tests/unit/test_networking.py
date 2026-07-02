"""Unit: network fabric model (cloud + host networking)."""
import unittest

from networking.fabric import (build_fabric, CrossCloudMesh,
                               PROVIDER_FABRIC_DEFAULTS)


class TestClusterFabric(unittest.TestCase):
    def test_host_networking_secure_defaults(self):
        f = build_fabric("c", "aws")
        h = f.host
        self.assertEqual(h.cni, "cilium")
        self.assertTrue(h.ebpf_dataplane)
        self.assertTrue(h.default_deny)
        self.assertTrue(h.sflow)
        self.assertEqual(h.mtls, "strict")

    def test_provider_primitive_mapping(self):
        self.assertEqual(build_fabric("c", "aws").hub_attachment, "transit-gateway")
        self.assertEqual(build_fabric("c", "gcp").interconnect, "dedicated-interconnect")
        self.assertEqual(build_fabric("c", "azure").edge.ddos_mitigation,
                         "azure-ddos-protection")

    def test_gpu_hosts_get_multi_nic(self):
        f = build_fabric("c", "baremetal", gpu=True)
        self.assertTrue(f.host.multi_nic)
        self.assertIn("eth1-rdma", f.host.nics)

    def test_all_providers_have_defaults(self):
        for p in ("aws", "gcp", "azure", "baremetal"):
            self.assertIn(p, PROVIDER_FABRIC_DEFAULTS)


class TestCrossCloudMesh(unittest.TestCase):
    def test_connect_records_private_encrypted_link(self):
        m = CrossCloudMesh()
        link = m.connect("aws", "gcp", transport="partner-interconnect", bandwidth_gbps=200)
        self.assertTrue(link.encrypted)
        self.assertEqual(link.bandwidth_gbps, 200)
        self.assertEqual(len(m.to_dict()["links"]), 1)


if __name__ == "__main__":
    unittest.main()
