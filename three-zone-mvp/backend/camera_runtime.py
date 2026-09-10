from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from .camera_adapters import CameraSource, adapter_for
from .db import dumps


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def materialize_camera_segment(db, object_store, *, camera_id: str, segment_path: Path, captured_at: float) -> str:
    object_id = str(uuid.uuid4())
    digest = sha256_file(segment_path)
    storage_key = f"camera/{camera_id}/{int(captured_at)}/{digest}.mp4"

    object_store.put(storage_key, segment_path)

    def _write(conn):
        conn.execute(
            "INSERT INTO camera_archive_objects(id,source_type,source_id,storage_key,sha256,recorded_at) "
            "VALUES (?,?,?,?,?,?)",
            (object_id, "camera", camera_id, storage_key, digest, captured_at),
        )
        conn.execute(
            "INSERT INTO camera_archive_verification_outbox(object_id,created_at,delivered_at) VALUES (?,?,NULL)",
            (object_id, captured_at),
        )
        payload = {"object_id": object_id, "camera_id": camera_id, "storage_key": storage_key, "sha256": digest}
        audit = conn.execute(
            "INSERT INTO audit(ts,actor,action,event_id,detail) VALUES (?,?,?,?,?)",
            (captured_at, "camera-supervisor", "media.object.created", camera_id, dumps(payload)),
        )
        audit_id = getattr(audit, "lastrowid", 0) or 0
        conn.execute(
            "INSERT INTO audit_verification_outbox(audit_id,event_json,created_at) VALUES (?,?,?)",
            (audit_id, dumps({"event_type": "media.object.created", "payload": payload}), captured_at),
        )

    db.write_transaction(_write)
    return object_id


class CameraSupervisor:
    def __init__(self, processes):
        self.processes = processes

    def reconcile(self, configured: list[CameraSource]) -> None:
        wanted = {camera.id: camera for camera in configured}
        running = set(self.processes.camera_ids())

        for camera_id in wanted.keys() - running:
            self.start(wanted[camera_id])
        for camera_id in running - wanted.keys():
            self.processes.stop(camera_id)

    def start(self, camera: CameraSource) -> None:
        adapter = adapter_for(camera)
        output = f"/capture/{camera.id}/%Y%m%d-%H%M%S.mp4"
        self.processes.start(camera.id, adapter.capture_command(output))
