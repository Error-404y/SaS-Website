"""Tests for verified visitor IP resolution and spoof-proof proxy boundaries."""
from email.message import Message
import unittest

import client_ips


class ClientIPTests(unittest.TestCase):
    @staticmethod
    def headers(*values):
        m=Message()
        for key,value in values:
            m.add_header(key,value)
        return m

    def test_unconfigured_proxy_mode_never_uses_shared_socket_ip(self):
        config=client_ips.configuration({})
        self.assertEqual(config.mode,"proxy")
        for headers in (self.headers(),
                        self.headers(("X-Forwarded-For","8.8.8.8")),
                        self.headers(("CF-Connecting-IP","1.1.1.1"))):
            result=client_ips.resolve("10.33.0.10",headers,config)
            self.assertEqual(result.ip,"")
            self.assertEqual(result.source,"unverified")

    def test_trust_only_exactly_configured_proxy_sources(self):
        config=client_ips.configuration({
            "SAS_CLIENT_IP_MODE":"proxy",
            "SAS_TRUSTED_PROXY_CIDRS":"10.33.0.10/32,2001:db8::1/128",
            "SAS_CLIENT_IP_HEADER":"X-Forwarded-For"})
        incoming=self.headers(("X-Forwarded-For","8.8.8.8"))
        self.assertEqual(client_ips.resolve("10.33.0.10",incoming,config),
                         client_ips.Identity("8.8.8.8","trusted_proxy"))
        self.assertEqual(client_ips.resolve("10.33.0.11",incoming,config).ip,"")
        self.assertEqual(client_ips.resolve("9.9.9.9",incoming,config).ip,"")
        self.assertEqual(client_ips.resolve("10.33.0.10",self.headers(),config).ip,"")

    def test_spoofed_first_xff_hop_is_not_used(self):
        config=client_ips.configuration({
            "SAS_CLIENT_IP_MODE":"proxy",
            "SAS_TRUSTED_PROXY_CIDRS":"10.33.0.10/32",
            "SAS_CLIENT_IP_HEADER":"x-forwarded-for"})
        # The proxy appended the real upstream IP after attacker-supplied junk.
        headers=self.headers(("X-Forwarded-For","9.9.9.9, 8.8.8.8"))
        identity=client_ips.resolve("10.33.0.10",headers,config)
        self.assertEqual(identity.ip,"8.8.8.8")
        self.assertEqual(identity.source,"trusted_proxy")
        # A trusted internal hop is skipped from the right side.
        headers=self.headers(("X-Forwarded-For","1.1.1.1, 8.8.4.4, 10.33.0.10"))
        self.assertEqual(client_ips.resolve("10.33.0.10",headers,config).ip,"8.8.4.4")

    def test_malformed_duplicate_or_private_forwarding_is_rejected(self):
        config=client_ips.configuration({
            "SAS_CLIENT_IP_MODE":"proxy",
            "SAS_TRUSTED_PROXY_CIDRS":"10.33.0.10/32",
            "SAS_CLIENT_IP_HEADER":"x-forwarded-for"})
        bad=[
            self.headers(("X-Forwarded-For","garbage")),
            self.headers(("X-Forwarded-For","8.8.8.8, no-ip")),
            self.headers(("X-Forwarded-For","192.168.0.1")),
            self.headers(("X-Forwarded-For","8.8.8.8, 10.1.1.1")),
            self.headers(("X-Forwarded-For","8.8.8.8:12345")),
            self.headers(("X-Forwarded-For","8.8.8.8"),
                         ("X-Forwarded-For","1.1.1.1")),
            self.headers(("X-Forwarded-For","8.8.8.8\nanother")),
        ]
        for index,headers in enumerate(bad):
            # One deliberately malformed header contains a newline, which
            # HTTPMessage cannot stringify; the resolver must still reject it.
            with self.subTest(case=index):
                self.assertEqual(client_ips.resolve("10.33.0.10",headers,config).ip,"")

    def test_single_value_header_and_v6(self):
        config=client_ips.configuration({
            "SAS_CLIENT_IP_MODE":"proxy",
            "SAS_TRUSTED_PROXY_CIDRS":"10.33.0.10/32",
            "SAS_CLIENT_IP_HEADER":"cf-connecting-ip"})
        self.assertEqual(client_ips.resolve("10.33.0.10",self.headers(
            ("CF-Connecting-IP","2606:4700:4700::1111")),config).ip,
            "2606:4700:4700::1111")
        self.assertEqual(client_ips.resolve("10.33.0.10",self.headers(
            ("CF-Connecting-IP","127.0.0.1")),config).ip,"")
        self.assertEqual(client_ips.resolve("10.33.0.10",self.headers(
            ("X-Forwarded-For","1.1.1.1")),config).ip,"")

    def test_explicit_direct_mode_ignores_forged_headers(self):
        config=client_ips.configuration({"SAS_CLIENT_IP_MODE":"direct"})
        result=client_ips.resolve("8.8.4.4",self.headers(
            ("X-Forwarded-For","1.1.1.1"),("CF-Connecting-IP","9.9.9.9")),config)
        self.assertEqual(result,client_ips.Identity("8.8.4.4","direct"))

    def test_invalid_proxy_configuration_fails_closed(self):
        for env in (
            {"SAS_CLIENT_IP_MODE":"proxy","SAS_CLIENT_IP_HEADER":"x-forwarded-for",
             "SAS_TRUSTED_PROXY_CIDRS":"0.0.0.0/0"},
            {"SAS_CLIENT_IP_MODE":"proxy","SAS_CLIENT_IP_HEADER":"x-forwarded-for",
             "SAS_TRUSTED_PROXY_CIDRS":"not-an-ip"},
            {"SAS_CLIENT_IP_MODE":"proxy","SAS_CLIENT_IP_HEADER":"unknown",
             "SAS_TRUSTED_PROXY_CIDRS":"10.33.0.10/32"},
            {"SAS_CLIENT_IP_MODE":"guess","SAS_CLIENT_IP_HEADER":"x-forwarded-for",
             "SAS_TRUSTED_PROXY_CIDRS":"10.33.0.10/32"},
        ):
            with self.subTest(env=env):
                self.assertEqual(client_ips.resolve("10.33.0.10",
                  self.headers(("X-Forwarded-For","8.8.8.8")),
                  client_ips.configuration(env)).ip,"")


if __name__=="__main__":
    unittest.main()
