import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.control_plane import ConflictError, ControlPlane
from backend.db import Database
from backend.seed import seed_if_empty
from backend.camera_runtime import materialize_camera_segment


class _ObjectStore:
    def __init__(self):
        self.writes = []

    def put(self, key, path):
        self.writes.append((key, Path(path)))


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        seed_if_empty(self.db)
        self.cp = ControlPlane(self.db, Config(env="demo", allowed_origins=["http://localhost"]))
        self.operator = self.cp.get_user("demo-owner")

    @patch("backend.camera_adapters.subprocess.run")
    def test_register_camera_stores_secret_refs_not_plaintext(self, run_mock):
        run_mock.return_value = SimpleNamespace(returncode=0, stderr="")
        camera = self.cp.register_camera(
            self.operator,
            {
                "name": "Warehouse 4",
                "endpoint": "rtsp://192.168.20.44:554/stream1",
                "username": "operator",
                "password": "secret-pass",
            },
        )
        self.assertEqual(camera["status"], "ready")
        self.assertTrue(camera["has_username"])
        self.assertTrue(camera["has_password"])
        row = self.db.query_one("SELECT * FROM camera_sources WHERE id=?", (camera["id"],))
        self.assertIsNotNone(row["username_secret_ref"])
        self.assertIsNotNone(row["password_secret_ref"])
        self.assertNotIn("secret-pass", str(dict(row)))
        self.assertEqual(len(self.cp.load_enabled_cameras()), 1)
        loaded = self.cp.load_enabled_cameras()[0]
        self.assertEqual(loaded.username, "operator")
        self.assertEqual(loaded.password, "secret-pass")

    @patch("backend.camera_adapters.subprocess.run")
    def test_register_camera_endpoint_must_be_unique(self, run_mock):
        run_mock.return_value = SimpleNamespace(returncode=0, stderr="")
        payload = {"name": "Warehouse 4", "endpoint": "rtsp://192.168.20.44:554/stream1"}
        self.cp.register_camera(self.operator, payload)
        with self.assertRaises(ConflictError):
            self.cp.register_camera(self.operator, payload)

    def test_materialize_camera_segment_creates_archive_and_outbox_records(self):
        store = _ObjectStore()
        with tempfile.TemporaryDirectory() as tmp:
            segment = Path(tmp) / "segment.mp4"
            segment.write_bytes(b"segment-data")
            object_id = materialize_camera_segment(
                self.db,
                store,
                camera_id="cam-1",
                segment_path=segment,
                captured_at=1_726_000_000.0,
            )
        self.assertTrue(store.writes)
        obj = self.db.query_one("SELECT * FROM camera_archive_objects WHERE id=?", (object_id,))
        self.assertIsNotNone(obj)
        outbox = self.db.query_one(
            "SELECT * FROM camera_archive_verification_outbox WHERE object_id=?",
            (object_id,),
        )
        self.assertIsNotNone(outbox)
        self.assertIsNone(outbox["delivered_at"])

    def test_station_camera_marks_production_ready_and_goes_live(self):
        created = self.cp.create_event(self.operator, {
            "title": "Gym cam",
            "zone": "midwest",
            "category": "basketball",
        })
        event_id = created["event_id"]
        self.assertEqual(created["status"], "scheduled")
        attached = self.cp.attach_station_camera(event_id, self.operator, go_live=False)
        self.assertTrue(attached["production_ready"])
        self.assertEqual(attached["camera"], "station")
        live = self.cp.attach_station_camera(event_id, self.operator, go_live=True)
        self.assertEqual(live["event"]["status"], "live")

    def test_station_camera_http_and_ops_slash_exist(self):
        import json
        import threading
        import urllib.request

        from backend.config import DEMO_SEED_PASSWORDS
        from backend.http_server import make_http_server

        cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                     allowed_origins=["http://127.0.0.1"])
        httpd = make_http_server(cfg, self.cp, "/tmp")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            with urllib.request.urlopen(base + "/ops/", timeout=5) as resp:
                ops = resp.read().decode()
            self.assertIn("Start camera", ops)
            self.assertIn("Go live with this camera", ops)
            login = urllib.request.Request(
                base + "/api/auth/login",
                data=json.dumps({
                    "username": "demo-owner",
                    "password": DEMO_SEED_PASSWORDS["demo-owner"],
                }).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(login, timeout=5) as resp:
                token = json.loads(resp.read())["session_token"]
            created = urllib.request.Request(
                base + "/api/events",
                data=json.dumps({"title": "Cam night", "zone": "midwest", "category": "basketball"}).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            )
            with urllib.request.urlopen(created, timeout=5) as resp:
                event_id = json.loads(resp.read())["event"]["event_id"]
            attach = urllib.request.Request(
                base + f"/api/events/{event_id}/camera/attach",
                data=json.dumps({"go_live": True, "source": "primary"}).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            )
            with urllib.request.urlopen(attach, timeout=5) as resp:
                payload = json.loads(resp.read())
            self.assertEqual(payload["event"]["status"], "live")
            self.assertTrue(payload["production_ready"])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
