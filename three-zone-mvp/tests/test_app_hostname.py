"""app.3zonesports.com DNS is IONOS → Lovable, not Cloudflare DNS."""

from __future__ import annotations

import http.server
import os
import sys
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "scripts"))
import check_app_hostname as check  # noqa: E402


def _ok_lookups():
    return {
        "app_a": {"google": [check.LOVABLE_EDGE_A], "cloudflare": [check.LOVABLE_EDGE_A]},
        "verify_txt": {
            "google": [f'"{check.VERIFY_TXT_PREFIX}abc"'],
            "cloudflare": [f"{check.VERIFY_TXT_PREFIX}abc"],
        },
        "apex_a": {"google": ["185.199.108.153"]},
        "app_aaaa": {"google": [], "cloudflare": []},
    }


class AppHostnameTests(unittest.TestCase):
    def test_connect_runbook_uses_ionos_not_cloudflare_dns(self):
        text = (ROOT / "three-zone-mvp" / "CONNECT-3ZONESPORTS.md").read_text(encoding="utf-8")
        self.assertIn("app.3zonesports.com", text)
        self.assertIn("185.158.133.1", text)
        self.assertIn("_lovable.app", text)
        self.assertIn("IONOS", text)
        self.assertIn("Cloudflare DNS zone you manage", text)
        self.assertIn("216.24.57.1", text)
        self.assertIn("scripts/check_app_hostname.py", text)

    def test_public_sign_in_lands_on_member_auth(self):
        config = (DOCS / "config.js").read_text(encoding="utf-8")
        self.assertIn("auth: '/auth'", config)
        self.assertIn("me: '/me'", config)
        self.assertIn("auth: '/#auth'", config)
        self.assertIn("me: '/#profile'", config)
        home = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/app/?to=auth"', home)
        self.assertIn('href="/app/?to=me"', home)
        site = (DOCS / "site.js").read_text(encoding="utf-8")
        self.assertIn("href: '/app/?to=auth'", site)
        self.assertEqual(
            (DOCS / "site.js").read_text(encoding="utf-8"),
            (ROOT / "main" / "site.js").read_text(encoding="utf-8"),
        )

    def test_evaluate_accepts_live_lovable_records(self):
        ok, warnings = check.evaluate(
            {
                "app_a": {"google": [check.LOVABLE_EDGE_A], "cloudflare": [check.LOVABLE_EDGE_A]},
                "verify_txt": {
                    "google": [f'"{check.VERIFY_TXT_PREFIX}abc"'],
                    "cloudflare": [f"{check.VERIFY_TXT_PREFIX}abc"],
                },
                "apex_a": {
                    "google": [check.RENDER_INGRESS_A, "185.199.108.153"],
                },
                "app_aaaa": {"google": [], "cloudflare": []},
            },
            https_status=200,
            acao=check.MEMBER_ORIGIN,
            alias_status=302,
            alias_location=check.MEMBER_ORIGIN + "/",
        )
        self.assertEqual(ok, [])
        self.assertTrue(any("216.24.57.1" in item for item in warnings))
        self.assertTrue(any("AAAA" in item for item in warnings))

    def test_evaluate_fails_closed_on_missing_app_record(self):
        failures, warnings = check.evaluate(
            {
                "app_a": {"google": [], "cloudflare": []},
                "verify_txt": {"google": [], "cloudflare": []},
                "apex_a": {"google": list(check.GITHUB_PAGES_A)},
                "app_aaaa": {"google": []},
            },
            https_status=0,
            acao=None,
        )
        self.assertGreaterEqual(len(failures), 3)
        self.assertTrue(any("expected 185.158.133.1" in item for item in failures))
        self.assertTrue(any("lovable_verify=" in item for item in failures))
        self.assertTrue(any("HTTP 0" in item for item in failures))
        self.assertTrue(any("CORS" in item for item in failures))

    def test_evaluate_fails_when_member_host_redirects_away(self):
        failures, _ = check.evaluate(
            _ok_lookups(),
            https_status=302,
            acao=check.MEMBER_ORIGIN,
            member_location=check.LOVABLE_ALIAS + "/",
            alias_status=302,
            alias_location=check.MEMBER_ORIGIN + "/",
        )
        self.assertTrue(any("without leaving the host" in item for item in failures))

    def test_evaluate_fails_when_lovable_alias_looks_like_200(self):
        failures, _ = check.evaluate(
            _ok_lookups(),
            https_status=200,
            acao=check.MEMBER_ORIGIN,
            alias_status=200,
            alias_location=None,
        )
        self.assertTrue(any("Lovable alias" in item for item in failures))
        self.assertTrue(any("expected a redirect" in item for item in failures))

    def test_evaluate_fails_when_lovable_alias_stays_on_lovable(self):
        failures, _ = check.evaluate(
            _ok_lookups(),
            https_status=200,
            acao=check.MEMBER_ORIGIN,
            alias_status=302,
            alias_location=check.LOVABLE_ALIAS + "/",
        )
        self.assertTrue(any("Lovable alias" in item for item in failures))

    def test_evaluate_accepts_relative_same_host_member_redirect(self):
        failures, _ = check.evaluate(
            _ok_lookups(),
            https_status=302,
            acao=check.MEMBER_ORIGIN,
            member_location="/auth",
            alias_status=302,
            alias_location=check.MEMBER_ORIGIN + "/",
        )
        self.assertEqual(failures, [])

    def test_evaluate_accepts_protocol_relative_alias_to_member(self):
        failures, _ = check.evaluate(
            _ok_lookups(),
            https_status=200,
            acao=check.MEMBER_ORIGIN,
            alias_status=302,
            alias_location="//app.3zonesports.com/",
        )
        self.assertEqual(failures, [])

    def test_evaluate_fails_relative_alias_that_stays_on_lovable(self):
        failures, _ = check.evaluate(
            _ok_lookups(),
            https_status=200,
            acao=check.MEMBER_ORIGIN,
            alias_status=302,
            alias_location="/",
        )
        self.assertTrue(any("Lovable alias" in item for item in failures))

    def test_redirect_origin_resolves_relative_and_protocol_relative(self):
        self.assertEqual(
            check._redirect_origin("/auth", check.MEMBER_ORIGIN + "/"),
            check.MEMBER_ORIGIN,
        )
        self.assertEqual(
            check._redirect_origin("//app.3zonesports.com/live", check.LOVABLE_ALIAS + "/"),
            check.MEMBER_ORIGIN,
        )
        self.assertEqual(
            check._redirect_origin("/", check.LOVABLE_ALIAS + "/"),
            check.LOVABLE_ALIAS,
        )
        self.assertEqual(
            check._redirect_origin("//evil.example/x", check.MEMBER_ORIGIN + "/"),
            "https://evil.example",
        )

    def test_request_does_not_follow_redirects(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/from":
                    self.send_response(302)
                    self.send_header("Location", "http://evil.example/followed")
                    self.end_headers()
                    self.wfile.write(b"redirect-body")
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"followed")

            def log_message(self, format, *args):
                return

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            port = httpd.server_address[1]
            status, headers, body = check._request(f"http://127.0.0.1:{port}/from")
            self.assertEqual(status, 302)
            self.assertEqual(check._header(headers, "Location"), "http://evil.example/followed")
            self.assertNotIn(b"followed", body)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_opener_installs_no_redirect_handler(self):
        opener = check._opener()
        self.assertTrue(any(isinstance(handler, check.NoRedirectHandler) for handler in opener.handlers))
        self.assertIsNone(
            check.NoRedirectHandler().redirect_request(None, None, 302, "Found", {}, "https://evil.example/")
        )


if __name__ == "__main__":
    os.chdir(str(ROOT / "three-zone-mvp"))
    unittest.main()
