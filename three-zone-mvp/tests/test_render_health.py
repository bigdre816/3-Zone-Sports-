"""Render health check: $PORT /healthz must be 200 and 8765 must not steal HTTP."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


MVP = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_http(url: str, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 — wait loop
            last = exc
            time.sleep(0.1)
    raise TimeoutError(f"{url} never became ready: {last}")


class RenderHealthProcessTests(unittest.TestCase):
    def test_render_port_serves_healthz_and_skips_ws_listen(self):
        http_port = _free_port()
        ws_port = _free_port()
        data_dir = tempfile.mkdtemp(prefix="tz-render-")
        env = os.environ.copy()
        env.update({
            "RENDER": "true",
            "PORT": str(http_port),
            "TZ_ENV": "demo",
            "TZ_HTTP_HOST": "127.0.0.1",
            "TZ_WS_HOST": "127.0.0.1",
            "TZ_WS_PORT": str(ws_port),
            "TZ_DATABASE_PATH": str(Path(data_dir) / "three_zone.sqlite3"),
            "TZ_DATA_DIR": data_dir,
            "TZ_ALLOWED_ORIGINS": "https://3zonesports.com",
            "RENDER_EXTERNAL_URL": f"http://127.0.0.1:{http_port}",
            "PYTHONUNBUFFERED": "1",
        })
        proc = subprocess.Popen(
            [sys.executable, "run.py", "--host", "127.0.0.1", "--http-port", str(http_port)],
            cwd=str(MVP),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            _wait_http(f"http://127.0.0.1:{http_port}/healthz")
            with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/healthz", timeout=5) as resp:
                payload = json.loads(resp.read())
                self.assertEqual(resp.status, 200)
                self.assertEqual(payload["status"], "ok")
            with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/api/health", timeout=5) as resp:
                self.assertEqual(json.loads(resp.read())["status"], "ok")
            # Member login is username/password, not demo-login-only.
            req = urllib.request.Request(
                f"http://127.0.0.1:{http_port}/api/auth/login",
                data=json.dumps({
                    "username": "demo-viewer",
                    "password": "change-me-viewer-local",
                }).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "X-Forwarded-Proto": "https"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                cookie = resp.headers.get("Set-Cookie") or ""
            self.assertEqual(body["home"], "/")
            self.assertIn("tz_member_session=", cookie)
            self.assertIn("Secure", cookie)
            # With the same-port gateway the hub is reachable on loopback only:
            # it is not a second public port, and the browser reaches it through
            # the one public port Render exposes.
            probe = socket.socket()
            probe.settimeout(0.5)
            try:
                loopback = probe.connect_ex(("127.0.0.1", ws_port))
            finally:
                probe.close()
            self.assertEqual(loopback, 0, "hub should listen on loopback behind the gateway")

            host_ip = socket.gethostbyname(socket.gethostname())
            if host_ip and not host_ip.startswith("127."):
                probe = socket.socket()
                probe.settimeout(0.5)
                try:
                    external = probe.connect_ex((host_ip, ws_port))
                finally:
                    probe.close()
                self.assertNotEqual(external, 0, "hub must not be publicly bound")

            # The advertised socket base must be a browser destination, never
            # a bind address, and it must ride the public origin.
            with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/api/config", timeout=5) as resp:
                cfg = json.loads(resp.read())
            self.assertTrue(cfg["ws_enabled"], cfg)
            self.assertTrue(cfg["ws_url_base"].startswith(("ws://", "wss://")), cfg)
            self.assertNotIn("0.0.0.0", cfg["ws_url_base"])
        finally:
            try:
                os.killpg(proc.pid, 15)
            except ProcessLookupError:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, 9)
                except ProcessLookupError:
                    proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    os.chdir(str(MVP))
    unittest.main()
