"""Public GitHub Pages site must not leak infrastructure or require a Connect step."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"

PUBLIC_PAGES = [
    DOCS / "index.html",
    DOCS / "404.html",
    DOCS / "live" / "index.html",
    DOCS / "schedules" / "index.html",
    DOCS / "archives" / "index.html",
    DOCS / "teams" / "index.html",
    DOCS / "schools" / "index.html",
    DOCS / "clips" / "index.html",
    DOCS / "app" / "index.html",
    DOCS / "styles.css",
    DOCS / "site.js",
]

FORBIDDEN_VISIBLE = (
    "onrender.com",
    "connect-form",
    "connect-url",
    "Member app starting",
    "Back portal",
    "back portal",
    "demo-viewer",
    "demo-owner",
    "demo-worker",
    "setMemberOrigin",
    "three-zone-api",
    "three-zone-sports-api",
)

CONNECT_BUTTON = re.compile(r">\s*Connect\s*<")
ERROR_INTERP = re.compile(r"error\.message")


class PublicSiteTests(unittest.TestCase):
    def test_public_html_never_renders_infrastructure(self):
        for path in PUBLIC_PAGES:
            text = path.read_text(encoding="utf-8")
            for needle in FORBIDDEN_VISIBLE:
                self.assertNotIn(needle, text, f"{path} leaked {needle!r}")
            self.assertIsNone(CONNECT_BUTTON.search(text), f"{path} still has a Connect button")
            self.assertNotIn('id="connect-form"', text)
            self.assertNotIn('id="connect-url"', text)
            self.assertNotIn("/ops", text)
            self.assertNotIn("data-ops-link", text)

    def test_config_has_one_production_render_origin(self):
        config = (DOCS / "config.js").read_text(encoding="utf-8")
        origins = re.findall(r"https://[a-z0-9.-]+\.onrender\.com", config)
        self.assertEqual(origins, ["https://three-zone-sports.onrender.com"])
        self.assertIn("const PRODUCTION_API_ORIGIN", config)
        self.assertNotIn("setMemberOrigin", config)
        self.assertNotIn("threezone_backend_url", config)
        self.assertNotIn("three-zone-api.onrender.com", config)
        self.assertNotIn("three-zone-sports-api.onrender.com", config)
        self.assertIn("/api/public/live", config)
        self.assertIn("/api/public/schedules", config)
        self.assertIn("/api/public/archives", config)

    def test_pages_fetch_public_catalog_automatically(self):
        home = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertIn("ThreeZoneSite.loadLive", home)
        self.assertIn("ThreeZoneSite.loadSchedules", home)
        self.assertIn("ThreeZoneSite.loadArchives", home)
        self.assertIn("Your sports. One place.", home)
        self.assertIn("Live Now", home)
        self.assertNotIn("Three Zones of Access", home)
        live = (DOCS / "live" / "index.html").read_text(encoding="utf-8")
        self.assertIn("ThreeZoneSite.loadLive", live)
        schedules = (DOCS / "schedules" / "index.html").read_text(encoding="utf-8")
        self.assertIn("ThreeZoneConfig.fetch(ThreeZoneConfig.endpoints.public.schedules)", schedules)
        archives = (DOCS / "archives" / "index.html").read_text(encoding="utf-8")
        self.assertIn("ThreeZoneSite.loadArchives", archives)

    def test_consumer_safe_failure_copy(self):
        site = (DOCS / "site.js").read_text(encoding="utf-8")
        self.assertIn("Games are temporarily unavailable. Try again shortly.", site)
        self.assertIn("Schedules are temporarily unavailable. Try again shortly.", site)
        self.assertIn("Replays are temporarily unavailable. Try again shortly.", site)
        self.assertIsNone(ERROR_INTERP.search(site))
        for path in PUBLIC_PAGES:
            if path.suffix == ".html":
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(ERROR_INTERP.search(text), path)

    def test_sign_in_stays_on_public_path(self):
        home = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/app/"', home)
        self.assertIn("Sign In", home)
        app = (DOCS / "app" / "index.html").read_text(encoding="utf-8")
        self.assertIn("memberAppUrl", app)


if __name__ == "__main__":
    os.chdir(str(REPO / "three-zone-mvp"))
    unittest.main()
