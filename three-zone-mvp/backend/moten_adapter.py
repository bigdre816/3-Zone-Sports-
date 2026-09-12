from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid

from .db import dumps, loads


class MotenIntakeService:
    """Queues non-blocking evidence handoffs from Three-Zone to Moten.

    Naming (Y1c / G0-C): this is a THREEZONE adapter/outbox client name, not a
    Treasure Network department or Path A review engine. Outbox delivery is
    transport only; Treasure release requires independent human seats.
    """

    def __init__(self, cp):
        self.cp = cp
        self.db = cp.db
        self.config = cp.config

    def discovery(self) -> dict:
        statuses = self.db.query(
            "SELECT status, COUNT(*) AS total FROM moten_outbox GROUP BY status ORDER BY status ASC"
        )
        return {
            "enabled": self.config.moten_enabled,
            "service_url": self.config.moten_service_url or None,
            "timeout_seconds": self.config.moten_timeout_seconds,
            "outbox": {row["status"]: row["total"] for row in statuses},
        }

    def status(self, job_id: str) -> dict:
        row = self.db.query_one("SELECT * FROM moten_outbox WHERE job_id=?", (job_id,))
        if not row:
            raise LookupError(job_id)
        return self._public_row(row)

    def handoff_event(self, operator: dict, event_id: str) -> dict:
        event = self.cp.get_event(event_id, operator)
        rights = self.cp.current_rights(event_id)
        payload = {
            "schema": "three-zone.moten.event.v1",
            "source_system": "three-zone-mvp",
            "source_service": "three-zone-api",
            "handoff_type": "event",
            "event_id": event_id,
            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "rights_version": rights["version"] if rights else None,
            "rights": dict(rights) if rights else None,
            "recent_audit": self._audit_rows(event_id, limit=10),
        }
        return self._enqueue("event", event_id, payload)

    def handoff_rights_version(self, operator: dict, event_id: str, version: int | None = None) -> dict:
        self.cp.require_operator(operator)
        version = int(version or 0) or None
        row = self.db.query_one(
            "SELECT * FROM rights WHERE event_id=? "
            + ("AND version=? " if version is not None else "")
            + "ORDER BY version DESC LIMIT 1",
            (event_id, version) if version is not None else (event_id,),
        )
        if not row:
            raise ValueError("rights version not found")
        payload = {
            "schema": "three-zone.moten.rights-version.v1",
            "source_system": "three-zone-mvp",
            "source_service": "three-zone-api",
            "handoff_type": "rights-version",
            "event_id": event_id,
            "object_version": f"rights-v{row['version']}",
            "rights_version": row["version"],
            "rights": dict(row),
            "recent_audit": self._audit_rows(event_id, limit=10),
        }
        return self._enqueue("rights-version", event_id, payload)

    def handoff_revocation_event(self, operator: dict, event_id: str) -> dict:
        self.cp.require_operator(operator)
        audit = self.db.query_one(
            "SELECT * FROM audit WHERE event_id=? AND action IN ('rights.revoked','rights.restored') "
            "ORDER BY id DESC LIMIT 1",
            (event_id,),
        )
        rights_rows = self.db.query(
            "SELECT * FROM rights WHERE event_id=? ORDER BY version DESC LIMIT 2",
            (event_id,),
        )
        if not audit:
            raise ValueError("no rights revocation or restore event found")
        payload = {
            "schema": "three-zone.moten.revocation-event.v1",
            "source_system": "three-zone-mvp",
            "source_service": "three-zone-api",
            "handoff_type": "revocation-event",
            "event_id": event_id,
            "audit": dict(audit),
            "rights_history": [dict(row) for row in rights_rows],
        }
        return self._enqueue("revocation-event", event_id, payload)

    def handoff_settlement(self, operator: dict, event_id: str) -> dict:
        manifest = self.cp.settlement_manifest(event_id, operator)
        payload = {
            "schema": "three-zone.moten.settlement.v1",
            "source_system": "three-zone-mvp",
            "source_service": "three-zone-api",
            "handoff_type": "settlement",
            "event_id": event_id,
            "settlement_id": manifest.get("settlement_id"),
            "rights_version": manifest.get("rights_version"),
            "settlement": manifest,
        }
        return self._enqueue("settlement", event_id, payload)

    def enqueue_runtime(self, handoff_type: str, source_object_id: str, payload: dict) -> dict:
        """Queue an evidence handoff from the member runtime (non-blocking)."""
        payload = dict(payload or {})
        payload.setdefault("schema", f"three-zone.moten.{handoff_type}.v1")
        payload.setdefault("source_system", "three-zone-mvp")
        payload.setdefault("source_service", "three-zone-api")
        payload.setdefault("handoff_type", handoff_type)
        payload.setdefault("occurred_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return self._enqueue(handoff_type, source_object_id, payload)

    def _audit_rows(self, event_id: str, limit: int) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM audit WHERE event_id=? ORDER BY id DESC LIMIT ?",
            (event_id, limit),
        )
        return [
            {
                "id": row["id"],
                "ts": row["ts"],
                "actor": row["actor"],
                "action": row["action"],
                "event_id": row["event_id"],
                "detail": loads(row["detail"], {}),
            }
            for row in rows
        ]

    def _enqueue(self, handoff_type: str, source_object_id: str, payload: dict) -> dict:
        stamp = time.time()
        job_id = f"mtn_{uuid.uuid4().hex[:16]}"
        initial_status = "queued" if self.config.moten_enabled else "skipped"
        last_error = None if self.config.moten_enabled else "moten service not configured"
        self.db.execute(
            "INSERT INTO moten_outbox(job_id,handoff_type,source_object_id,payload_json,status,attempts,"
            "response_status,response_body,last_error,created_at,updated_at,delivered_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                handoff_type,
                source_object_id,
                dumps(payload),
                initial_status,
                0,
                None,
                None,
                last_error,
                stamp,
                stamp,
                None,
            ),
        )
        if self.config.moten_enabled:
            thread = threading.Thread(target=self._deliver, args=(job_id,), daemon=True)
            thread.start()
        return self.status(job_id)

    def _deliver(self, job_id: str) -> None:
        row = self.db.query_one("SELECT * FROM moten_outbox WHERE job_id=?", (job_id,))
        if not row:
            return
        payload = loads(row["payload_json"], {})
        body = dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.moten_service_url}/intake/{row['handoff_type']}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Moten-Shared-Secret": self.config.moten_shared_secret,
                "X-Three-Zone-Source": "three-zone-api",
            },
        )
        attempts = int(row["attempts"] or 0) + 1
        try:
            with urllib.request.urlopen(request, timeout=self.config.moten_timeout_seconds) as resp:
                response_body = resp.read().decode("utf-8")
                self.db.execute(
                    "UPDATE moten_outbox SET status=?, attempts=?, response_status=?, response_body=?, "
                    "last_error=?, updated_at=?, delivered_at=? WHERE job_id=?",
                    ("delivered", attempts, resp.status, response_body, None, time.time(), time.time(), job_id),
                )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.db.execute(
                "UPDATE moten_outbox SET status=?, attempts=?, response_status=?, response_body=?, "
                "last_error=?, updated_at=? WHERE job_id=?",
                ("failed", attempts, exc.code, detail, f"http_{exc.code}", time.time(), job_id),
            )
        except Exception as exc:
            self.db.execute(
                "UPDATE moten_outbox SET status=?, attempts=?, last_error=?, updated_at=? WHERE job_id=?",
                ("failed", attempts, str(exc), time.time(), job_id),
            )

    @staticmethod
    def _public_row(row) -> dict:
        return {
            "job_id": row["job_id"],
            "handoff_type": row["handoff_type"],
            "source_object_id": row["source_object_id"],
            "status": row["status"],
            "attempts": row["attempts"],
            "response_status": row["response_status"],
            "response_body": loads(row["response_body"], row["response_body"]),
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "delivered_at": row["delivered_at"],
        }
