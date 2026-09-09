from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config, DEMO_SEED_PASSWORDS
from backend.control_plane import ControlPlane
from backend.db import Database
from backend.http_server import make_http_server
from backend.seed import seed_if_empty


class _MotenHandler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.calls.append(
            {
                "path": self.path,
                "secret": self.headers.get("X-Moten-Shared-Secret"),
                "payload": json.loads(body),
            }
        )
        payload = json.dumps({"accepted": True, "path": self.path}).encode("utf-8")
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class MotenIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        seed_if_empty(self.db)
        self.moten = ThreadingHTTPServer(("127.0.0.1", 0), _MotenHandler)
        _MotenHandler.calls = []
        self.moten_thread = threading.Thread(target=self.moten.serve_forever, daemon=True)
        self.moten_thread.start()
        moten_base = f"http://127.0.0.1:{self.moten.server_address[1]}"
        self.cp = ControlPlane(
            self.db,
            Config(
                env="demo",
                http_host="127.0.0.1",
                http_port=0,
                allowed_origins=["http://127.0.0.1"],
                token_secret="x" * 40,
                media_service_key="y" * 40,
                moten_service_url=moten_base,
                moten_shared_secret="shared-secret",
            ),
        )
        self.httpd = make_http_server(self.cp.config, self.cp, "/tmp")
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.http_thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.operator_token = self.cp.password_login("demo-owner", DEMO_SEED_PASSWORDS["demo-owner"])["session_token"]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.moten.shutdown()
        self.moten.server_close()
        self.db.close()

    def _json(self, method: str, path: str, body: dict | None = None):
        request = Request(
            self.base + path,
            data=json.dumps(body or {}).encode("utf-8") if method == "POST" else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.operator_token,
            },
        )
        with urlopen(request, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def test_event_handoff_is_queued_and_delivered_async(self):
        status, discovery = self._json("GET", "/api/moten/discovery")
        self.assertEqual(status, 200)
        self.assertTrue(discovery["enabled"])

        status, job = self._json("POST", "/api/moten/intake/event", {"event_id": "evt_mw_basketball"})
        self.assertEqual(status, 202)
        self.assertEqual(job["handoff_type"], "event")
        self.assertIn(job["status"], ("queued", "delivered"))

        for _ in range(40):
            _, polled = self._json("GET", f"/api/moten/intake/jobs/{job['job_id']}")
            if polled["status"] == "delivered":
                break
            time.sleep(0.05)
        self.assertEqual(polled["status"], "delivered")
        self.assertEqual(polled["response_status"], 202)
        self.assertEqual(len(_MotenHandler.calls), 1)
        self.assertEqual(_MotenHandler.calls[0]["path"], "/intake/event")
        self.assertEqual(_MotenHandler.calls[0]["secret"], "shared-secret")
        self.assertEqual(_MotenHandler.calls[0]["payload"]["event_id"], "evt_mw_basketball")

    def test_database_url_is_preferred_when_present(self):
        cfg = Config(database_url="postgresql://db/render", database_path="ignored.sqlite3")
        self.assertEqual(cfg.database_locator, "postgresql://db/render")


if __name__ == "__main__":
    unittest.main()
