"""The gateway, not the visitor, decides the per-IP accounting key.

Behind the same-port gateway every HTTP request reaches the internal server
from loopback. Without a canonical client-IP header the per-IP login limit and
the per-IP socket cap collapse into one global bucket; with a *spoofable* one
a visitor simply picks a fresh bucket. Both regressions fail here.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MVP))

from backend import gateway  # noqa: E402


def _head(extra: str = "") -> bytes:
    return (
        "GET /api/config HTTP/1.1\r\n"
        "Host: example.onrender.com\r\n"
        f"{extra}"
        "\r\n"
    ).encode()


def _headers(head: bytes) -> list[str]:
    return [line for line in head.decode().split("\r\n") if ":" in line]


class GatewayClientIpTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("TZ_TRUST_UPSTREAM_PROXY", None)

    def test_inbound_client_ip_headers_are_stripped(self):
        os.environ["TZ_TRUST_UPSTREAM_PROXY"] = "0"
        head = gateway._with_client_ip(
            _head("X-TZ-Client-IP: 9.9.9.9\r\nX-Forwarded-For: 9.9.9.9\r\n"),
            "203.0.113.7",
        )
        headers = _headers(head)
        self.assertEqual(
            [h for h in headers if h.lower().startswith("x-tz-client-ip")],
            ["X-TZ-Client-IP: 203.0.113.7"],
        )
        self.assertEqual(
            [h for h in headers if h.lower().startswith("x-forwarded-for")],
            ["X-Forwarded-For: 203.0.113.7"],
        )
        self.assertNotIn("9.9.9.9", head.decode())

    def test_trusted_upstream_proxy_supplies_the_real_visitor(self):
        os.environ["TZ_TRUST_UPSTREAM_PROXY"] = "1"
        head = gateway._with_client_ip(
            _head("X-Forwarded-For: 198.51.100.4, 10.0.0.9\r\n"),
            "10.0.0.9",
        )
        self.assertIn("X-TZ-Client-IP: 198.51.100.4", _headers(head))

    def test_body_and_request_line_survive_the_rewrite(self):
        os.environ["TZ_TRUST_UPSTREAM_PROXY"] = "0"
        raw = (
            b"POST /api/auth/login HTTP/1.1\r\nHost: h\r\nContent-Length: 4\r\n\r\nbody"
        )
        head = gateway._with_client_ip(raw, "203.0.113.9")
        self.assertTrue(head.startswith(b"POST /api/auth/login HTTP/1.1\r\n"))
        self.assertTrue(head.endswith(b"\r\n\r\nbody"))


if __name__ == "__main__":
    os.chdir(str(MVP))
    unittest.main()
