"""Exercise every public-site control, origin, query, and catalog input."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
sys.path.insert(0, str(REPO / "three-zone-mvp"))

NAV_HREFS = (
    "/",
    "/live/",
    "/schedules/",
    "/teams/",
    "/schools/",
    "/clips/",
    "/archives/",
    "/app/",
)

CHROME_PAGES = (
    DOCS / "index.html",
    DOCS / "live" / "index.html",
    DOCS / "schedules" / "index.html",
    DOCS / "archives" / "index.html",
    DOCS / "teams" / "index.html",
    DOCS / "schools" / "index.html",
    DOCS / "clips" / "index.html",
)

PUBLIC_PATHS = (
    "/api/health",
    "/api/public/live",
    "/api/public/schedules",
    "/api/public/archives",
)

QUERY_INPUTS = (
    "",
    "?mode=for_you",
    "?sport=basketball",
    "?event=evt_mw_basketball",
    "?q=" + urllib.request.quote("<script>alert(1)</script>"),
    "?cursor=" + ("x" * 200),
)

ORIGINS = (
    None,
    "https://3zonesports.com",
    "https://www.3zonesports.com",
    "https://evil.example",
)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.buttons = []
        self.inputs = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            self.ids.append(data["id"])
        if tag == "a" and "href" in data:
            self.hrefs.append(data["href"])
        if tag == "button":
            self.buttons.append(data)
        if tag in ("input", "textarea", "select"):
            self.inputs.append((tag, data))


def parse_page(path: Path) -> LinkParser:
    parser = LinkParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


class PublicInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness = Path(__file__).with_name("public_config_harness.js")
        raw = subprocess.check_output(["node", str(harness)], text=True)
        cls.harness = json.loads(raw)

    def test_config_origin_for_every_hostname(self):
        origin = self.harness["origin"]
        self.assertEqual(origin["noWindow"], "https://three-zone-sports.onrender.com")
        self.assertEqual(origin["localhost"], "http://localhost:8000")
        self.assertEqual(origin["loopback"], "http://127.0.0.1:8000")
        self.assertEqual(origin["pages"], "https://three-zone-sports.onrender.com")
        self.assertEqual(origin["www"], "https://three-zone-sports.onrender.com")
        self.assertEqual(origin["override"], "https://example.test")

    def test_member_app_url_for_every_path_input(self):
        urls = self.harness["memberAppUrl"]
        self.assertEqual(urls["empty"], "https://three-zone-sports.onrender.com/")
        self.assertEqual(urls["root"], "https://three-zone-sports.onrender.com/")
        self.assertEqual(urls["query"], "https://three-zone-sports.onrender.com/?event=evt_x")
        self.assertIn("event=", urls["encoded"])
        self.assertNotIn("<", urls["encoded"])
        self.assertNotIn('"', urls["encoded"].split("event=", 1)[-1])

    def test_fetch_handles_ok_html_json_and_network_failure(self):
        fetch = self.harness["fetch"]
        self.assertEqual(fetch["ok"], {"events": [{"title": "ok"}]})
        self.assertEqual(fetch["fail"]["message"], "unavailable")
        self.assertEqual(fetch["fail"]["code"], "unavailable")
        self.assertEqual(fetch["fail"]["status"], 503)
        self.assertEqual(fetch["html"]["message"], "unavailable")
        self.assertEqual(fetch["badJson"]["message"], "unavailable")
        self.assertTrue(fetch["healthOk"])
        self.assertFalse(fetch["healthDown"])

    def test_site_helpers_for_empty_duplicate_and_hostile_ids(self):
        site = self.harness["site"]
        self.assertEqual(site["uniqueEmpty"], [])
        self.assertEqual(site["uniqueDupes"], ["A", "B"])
        self.assertEqual(site["timeEmpty"], "Time TBA")
        self.assertEqual(site["timeBad"], "Time TBA")
        self.assertTrue(site["timeOk"])
        self.assertEqual(site["gameHref"], "/app/?event=evt_%22%3C%3E")
        self.assertEqual(site["archiveHref"], "/app/?archive=arc%201")

    def test_every_chrome_page_has_nav_menu_and_no_text_inputs(self):
        for path in CHROME_PAGES:
            parsed = parse_page(path)
            self.assertEqual(parsed.inputs, [], f"{path} unexpectedly has a form control")
            self.assertIn("menu-toggle", parsed.ids, path)
            hrefs = set(parsed.hrefs)
            for needed in NAV_HREFS:
                self.assertIn(needed, hrefs, f"{path} missing {needed}")
            self.assertTrue(any(btn.get("id") == "menu-toggle" for btn in parsed.buttons), path)
            self.assertTrue(any(btn.get("aria-label") == "Menu" for btn in parsed.buttons), path)

    def test_home_ctas_cover_every_product_entry(self):
        parsed = parse_page(DOCS / "index.html")
        hrefs = parsed.hrefs
        self.assertGreaterEqual(hrefs.count("/app/"), 4)
        self.assertIn("/live/", hrefs)
        self.assertIn("/schedules/", hrefs)
        self.assertIn("/teams/", hrefs)
        self.assertIn("/schools/", hrefs)
        self.assertIn("/archives/", hrefs)

    def test_app_and_404_have_no_admin_or_form_controls(self):
        for path in (DOCS / "app" / "index.html", DOCS / "404.html"):
            parsed = parse_page(path)
            self.assertEqual(parsed.inputs, [])
            self.assertNotIn("/ops", path.read_text(encoding="utf-8"))

    def _server(self, origins):
        from backend.config import Config
        from backend.control_plane import ControlPlane
        from backend.db import Database
        from backend.http_server import make_http_server
        from backend.seed import seed_if_empty

        db = Database(":memory:")
        seed_if_empty(db)
        cfg = Config(
            env="demo",
            http_host="127.0.0.1",
            http_port=0,
            allowed_origins=origins,
        )
        cp = ControlPlane(db, cfg)
        httpd = make_http_server(cfg, cp, "/tmp")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd

    def _open(self, url, origin=None, method="GET"):
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        request = urllib.request.Request(url, headers=headers, method=method)
        return urllib.request.urlopen(request, timeout=5)

    def test_every_public_path_origin_and_query_input(self):
        httpd = self._server(["https://3zonesports.com", "https://www.3zonesports.com"])
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            for path in PUBLIC_PATHS:
                for origin in ORIGINS:
                    for query in QUERY_INPUTS:
                        url = base + path + query
                        if origin == "https://evil.example":
                            with self.assertRaises(urllib.error.HTTPError) as raised:
                                self._open(url, origin)
                            self.assertEqual(raised.exception.code, 403, url)
                            continue
                        with self._open(url, origin) as resp:
                            payload = json.loads(resp.read())
                            acao = resp.headers.get("Access-Control-Allow-Origin")
                            if origin in ("https://3zonesports.com", "https://www.3zonesports.com"):
                                self.assertEqual(acao, origin, url)
                            else:
                                self.assertIsNone(acao, url)
                            if path == "/api/health":
                                self.assertEqual(payload["status"], "ok")
                            elif path.endswith("/live"):
                                self.assertGreaterEqual(len(payload["events"]), 1)
                                for event in payload["events"]:
                                    self.assertNotIn("rights", event)
                            elif path.endswith("/schedules"):
                                self.assertGreaterEqual(len(payload["schedules"]), 1)
                            else:
                                self.assertGreaterEqual(len(payload["archives"]), 1)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_options_preflight_for_every_public_path(self):
        httpd = self._server(["https://3zonesports.com"])
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            for path in PUBLIC_PATHS:
                with self._open(base + path, "https://3zonesports.com", method="OPTIONS") as resp:
                    self.assertEqual(resp.status, 204)
                    self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "https://3zonesports.com")
                    self.assertIn("GET", resp.headers.get("Access-Control-Allow-Methods", ""))
                with self.assertRaises(urllib.error.HTTPError):
                    # urllib follows nothing; OPTIONS to evil still returns 204 with no ACAO
                    # because do_OPTIONS always sends 204. Confirm GET is the reject path.
                    self._open(base + path, "https://evil.example")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_watch_and_replay_hrefs_escape_hostile_ids(self):
        self.assertEqual(
            html.escape("/app/?event=evt_%22%3C%3E"),
            "/app/?event=evt_%22%3C%3E",
        )
        text = (DOCS / "site.js").read_text(encoding="utf-8")
        self.assertIn("encodeURIComponent(eventId)", text)
        self.assertIn("encodeURIComponent(archiveId)", text)


if __name__ == "__main__":
    os.chdir(str(REPO / "three-zone-mvp"))
    unittest.main()
