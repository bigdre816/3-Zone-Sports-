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


if __name__ == "__main__":
    unittest.main()
