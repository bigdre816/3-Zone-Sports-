"""app.3zonesports.com DNS is IONOS → Lovable, not Cloudflare DNS."""

from __future__ import annotations

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


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
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import check_app_hostname as check

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
        )
        self.assertEqual(ok, [])
        self.assertTrue(any("216.24.57.1" in item for item in warnings))
        self.assertTrue(any("AAAA" in item for item in warnings))

    def test_evaluate_fails_closed_on_missing_app_record(self):
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import check_app_hostname as check

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


if __name__ == "__main__":
    os.chdir(str(ROOT / "three-zone-mvp"))
    unittest.main()
