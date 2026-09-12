"""Y5 — Treasure delivery + reconciliation for transcription proposals.

THREEZONE prepares a complete Path A **producer handoff** packet so it can talk
to Treasure Network with required information. Canonical packet/revision,
Reviewer 1 / Reviewer 2 / Release Authority seats, and release stay in Treasure.

Transport honesty (Y1c / G0-C): successful Moten/control-plane intake is
``intake_accepted`` only — never bare ``accepted`` as governance, never
``treasure_release=true``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from threezone_ai.proposals.types import (
    PROPOSAL_SCHEMA_REF,
    ProposalNotFound,
    TranscriptionProposal,
    canonical_json,
)

# Packet taxonomy (G0-C) — family THREEZONE; this slice is media transcript.
PACKET_FAMILY = "THREEZONE"
PACKET_TYPE = "THREEZONE_MEDIA_TRANSCRIPT"

DELIVERY_SCHEMA = "three-zone.moten.transcription-proposal.v1"
DELIVERY_SCHEMA_ALT = "threezone.treasure.proposal.delivery.v0"
HANDOFF_TYPE = "transcription-proposal"

# Local outbox / transport statuses (THREEZONE-owned delivery receipts).
STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_INTAKE_ACCEPTED = "intake_accepted"
STATUS_MISMATCH = "mismatch"

TRANSPORT_STATUSES = frozenset(
    {
        STATUS_PENDING,
        STATUS_QUEUED,
        STATUS_SKIPPED,
        STATUS_FAILED,
        STATUS_INTAKE_ACCEPTED,
        STATUS_MISMATCH,
    }
)

# Proposal-side delivery-state vocabulary projection (submitted → intake_accepted).
DELIVERY_STATE_SUBMITTED = "submitted"
DELIVERY_STATE_QUEUED = "queued_for_delivery"
DELIVERY_STATE_INTAKE_ACCEPTED = "intake_accepted"
DELIVERY_STATE_FAILED = "failed"
DELIVERY_STATE_SKIPPED = "skipped"
DELIVERY_STATE_MISMATCH = "mismatch"


class DeliveryError(Exception):
    status = 400
    code = "delivery_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class MotenDisabled(DeliveryError):
    """Fail-closed when Moten/Treasure intake URL is not configured."""

    status = 503
    code = "moten_disabled"


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, separators=(",", ":"), sort_keys=True)


def _loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def _now(now: float | None = None) -> float:
    return float(now if now is not None else time.time())


def _stamp_iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_now(ts)))


def _new_delivery_id() -> str:
    return f"tdl_{uuid.uuid4().hex[:16]}"


OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS treasure_delivery_outbox (
    delivery_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    job_id TEXT,
    content_hash TEXT NOT NULL,
    handoff_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    response_status INTEGER,
    response_body TEXT,
    response_metadata_json TEXT,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    delivered_at REAL,
    canonical_packet_id TEXT,
    canonical_revision_id TEXT,
    canonical_status TEXT
);
CREATE INDEX IF NOT EXISTS idx_tdel_proposal ON treasure_delivery_outbox(proposal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tdel_status ON treasure_delivery_outbox(status, created_at);
CREATE INDEX IF NOT EXISTS idx_tdel_hash ON treasure_delivery_outbox(proposal_id, content_hash);
"""


@dataclass
class DeliveryReceipt:
    """Local THREEZONE delivery receipt (transport only)."""

    delivery_id: str
    proposal_id: str
    job_id: str | None
    content_hash: str
    handoff_type: str = HANDOFF_TYPE
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_PENDING
    attempts: int = 0
    response_status: int | None = None
    response_body: Any = None
    response_metadata: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    delivered_at: float | None = None
    # Read-only Treasure projections when known — never invent seats.
    canonical_packet_id: str | None = None
    canonical_revision_id: str | None = None
    canonical_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "proposal_id": self.proposal_id,
            "job_id": self.job_id,
            "content_hash": self.content_hash,
            "handoff_type": self.handoff_type,
            "payload": dict(self.payload or {}),
            "status": self.status,
            "attempts": self.attempts,
            "response_status": self.response_status,
            "response_body": self.response_body,
            "response_metadata": dict(self.response_metadata or {}),
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "delivered_at": self.delivered_at,
            "canonical_packet_id": self.canonical_packet_id,
            "canonical_revision_id": self.canonical_revision_id,
            "canonical_status": self.canonical_status,
            # Explicit bans / honesty
            "treasure_release": False,
            "governance": "none",
            "means": "intake_accepted_transport_only"
            if self.status == STATUS_INTAKE_ACCEPTED
            else "transport_pending_or_failed",
            # Never expose bare "accepted" as governance status.
            "intake_accepted": self.status == STATUS_INTAKE_ACCEPTED,
        }


def _row_to_receipt(row: sqlite3.Row) -> DeliveryReceipt:
    return DeliveryReceipt(
        delivery_id=row["delivery_id"],
        proposal_id=row["proposal_id"],
        job_id=row["job_id"],
        content_hash=row["content_hash"],
        handoff_type=row["handoff_type"] or HANDOFF_TYPE,
        payload=_loads(row["payload_json"], {}) or {},
        status=row["status"] or STATUS_PENDING,
        attempts=int(row["attempts"] or 0),
        response_status=row["response_status"],
        response_body=_loads(row["response_body"], row["response_body"]),
        response_metadata=_loads(row["response_metadata_json"], {}) or {},
        last_error=row["last_error"],
        created_at=float(row["created_at"] or 0),
        updated_at=float(row["updated_at"] or 0),
        delivered_at=float(row["delivered_at"]) if row["delivered_at"] is not None else None,
        canonical_packet_id=row["canonical_packet_id"],
        canonical_revision_id=row["canonical_revision_id"],
        canonical_status=row["canonical_status"],
    )


class TreasureDeliveryOutbox:
    """Isolated SQLite outbox for Treasure proposal delivery receipts."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = threading.RLock()
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        with self._lock:
            self._conn.executescript(OUTBOX_SCHEMA)
            self._conn.commit()

    def insert(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        with self._lock:
            self._conn.execute(
                "INSERT INTO treasure_delivery_outbox("
                "delivery_id, proposal_id, job_id, content_hash, handoff_type, payload_json,"
                " status, attempts, response_status, response_body, response_metadata_json,"
                " last_error, created_at, updated_at, delivered_at,"
                " canonical_packet_id, canonical_revision_id, canonical_status"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt.delivery_id,
                    receipt.proposal_id,
                    receipt.job_id,
                    receipt.content_hash,
                    receipt.handoff_type,
                    _dumps(receipt.payload),
                    receipt.status,
                    receipt.attempts,
                    receipt.response_status,
                    _dumps(receipt.response_body)
                    if not isinstance(receipt.response_body, str)
                    else receipt.response_body,
                    _dumps(receipt.response_metadata),
                    receipt.last_error,
                    receipt.created_at,
                    receipt.updated_at,
                    receipt.delivered_at,
                    receipt.canonical_packet_id,
                    receipt.canonical_revision_id,
                    receipt.canonical_status,
                ),
            )
            self._conn.commit()
        return receipt

    def update(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        with self._lock:
            self._conn.execute(
                "UPDATE treasure_delivery_outbox SET status=?, attempts=?, response_status=?,"
                " response_body=?, response_metadata_json=?, last_error=?, updated_at=?,"
                " delivered_at=?, canonical_packet_id=?, canonical_revision_id=?,"
                " canonical_status=?, payload_json=? WHERE delivery_id=?",
                (
                    receipt.status,
                    receipt.attempts,
                    receipt.response_status,
                    _dumps(receipt.response_body)
                    if not isinstance(receipt.response_body, str)
                    else receipt.response_body,
                    _dumps(receipt.response_metadata),
                    receipt.last_error,
                    receipt.updated_at,
                    receipt.delivered_at,
                    receipt.canonical_packet_id,
                    receipt.canonical_revision_id,
                    receipt.canonical_status,
                    _dumps(receipt.payload),
                    receipt.delivery_id,
                ),
            )
            self._conn.commit()
        return receipt

    def get(self, delivery_id: str) -> DeliveryReceipt | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM treasure_delivery_outbox WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        return _row_to_receipt(row) if row else None

    def latest_for_proposal(self, proposal_id: str) -> DeliveryReceipt | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM treasure_delivery_outbox WHERE proposal_id=?"
                " ORDER BY created_at DESC, delivery_id DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        return _row_to_receipt(row) if row else None

    def latest_intake_accepted(
        self, proposal_id: str, content_hash: str
    ) -> DeliveryReceipt | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM treasure_delivery_outbox WHERE proposal_id=?"
                " AND content_hash=? AND status=? "
                "ORDER BY created_at DESC LIMIT 1",
                (proposal_id, content_hash, STATUS_INTAKE_ACCEPTED),
            ).fetchone()
        return _row_to_receipt(row) if row else None

    def list_for_proposal(self, proposal_id: str) -> list[DeliveryReceipt]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM treasure_delivery_outbox WHERE proposal_id=?"
                " ORDER BY created_at ASC",
                (proposal_id,),
            ).fetchall()
        return [_row_to_receipt(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def build_delivery_payload(
    proposal: TranscriptionProposal,
    *,
    producer: dict[str, Any] | None = None,
    lineage: dict[str, Any] | None = None,
    job_result: dict[str, Any] | None = None,
    occurred_at: float | None = None,
) -> dict[str, Any]:
    """Complete Path A producer handoff packet (THREEZONE → Treasure talk).

    Does **not** include Reviewer 1 / Reviewer 2 / Release seats.
    """
    result = job_result if isinstance(job_result, dict) else {}
    lineage_info: dict[str, Any] = {}
    if proposal.lineage_id:
        lineage_info["lineage_id"] = proposal.lineage_id
    if lineage:
        lineage_info.update({k: v for k, v in lineage.items() if v is not None})
    # Prefer explicit lineage; fall back to job result fields when available.
    for key in ("provider", "model", "version"):
        if key not in lineage_info or lineage_info.get(key) is None:
            val = result.get(key) or (proposal.provider if key == "provider" else None)
            if val is not None:
                lineage_info[key] = val

    producer_info = {
        "source_system": "three-zone-mvp",
        "source_service": "three-zone-api",
        "role": "producer",
    }
    if producer:
        producer_info.update({k: v for k, v in producer.items() if v is not None})

    segments = list(proposal.segments or [])
    segments_ref = f"proposal:{proposal.proposal_id}:segments"

    payload: dict[str, Any] = {
        "schema": DELIVERY_SCHEMA,
        "schema_alt": DELIVERY_SCHEMA_ALT,
        "source_system": "three-zone-mvp",
        "source_service": "three-zone-api",
        "handoff_type": HANDOFF_TYPE,
        "packet_family": PACKET_FAMILY,
        "packet_type": PACKET_TYPE,
        "proposal_id": proposal.proposal_id,
        "job_id": proposal.job_id,
        "source_asset_id": proposal.source_asset_id,
        "object_id": proposal.proposal_id,
        "object_version": proposal.schema_ref or PROPOSAL_SCHEMA_REF,
        "content_hash": proposal.content_hash,
        "proposal_schema_ref": proposal.schema_ref or PROPOSAL_SCHEMA_REF,
        "segments_ref": segments_ref,
        "segments": segments,
        "segment_count": len(segments),
        "publish": False,
        "treasure_release": False,
        "human_review_required": True,
        "proposal_status": proposal.status,
        "proposal_kind": "transcription_proposal",
        "producer": producer_info,
        "lineage": lineage_info or None,
        "provenance": {
            "content_hash": proposal.content_hash,
            "proposal_id": proposal.proposal_id,
            "job_id": proposal.job_id,
            "source_asset_id": proposal.source_asset_id,
            "lineage_id": proposal.lineage_id,
            "provider": lineage_info.get("provider") if lineage_info else proposal.provider,
            "created_at": proposal.created_at,
        },
        # Delivery-state start; transport updates local outbox to intake_accepted.
        "delivery_state": DELIVERY_STATE_SUBMITTED,
        # Projections only — null until Treasure returns them; never invent seats.
        "canonical_packet_id": None,
        "canonical_revision_id": None,
        "canonical_status": None,
        "path_a": {
            "lane": "THREEZONE_evidence",
            "producer_handoff": True,
            "seats_in_threezone": False,
            "note": "Reviewer1/Reviewer2/ReleaseAuthority remain in Treasure",
        },
        "occurred_at": _stamp_iso(occurred_at),
        # Transport honesty markers (never governance "accepted")
        "means": "producer_handoff_packet",
        "governance": "none",
    }
    return payload


def _map_delivery_state(outbox_status: str | None) -> str:
    if not outbox_status or outbox_status == STATUS_PENDING:
        return DELIVERY_STATE_SUBMITTED
    if outbox_status == STATUS_QUEUED:
        return DELIVERY_STATE_QUEUED
    if outbox_status == STATUS_INTAKE_ACCEPTED:
        return DELIVERY_STATE_INTAKE_ACCEPTED
    if outbox_status == STATUS_SKIPPED:
        return DELIVERY_STATE_SKIPPED
    if outbox_status == STATUS_FAILED:
        return DELIVERY_STATE_FAILED
    if outbox_status == STATUS_MISMATCH:
        return DELIVERY_STATE_MISMATCH
    return DELIVERY_STATE_SUBMITTED


def _extract_projections(response_body: Any) -> dict[str, Any]:
    """Pull optional Treasure projections from intake response — never invent seats."""
    body = response_body if isinstance(response_body, dict) else {}
    banned_keys = {
        "reviewer_1",
        "reviewer_2",
        "release_authority",
        "r1",
        "r2",
        "review_1_pending",
        "review_2_pending",
        "released",
    }
    out: dict[str, Any] = {}
    for key in ("canonical_packet_id", "canonical_revision_id", "canonical_status", "intake_id"):
        if key in body and body[key] is not None:
            out[key] = body[key]
    # Explicitly ignore any seat fields if a buggy remote sent them.
    for k in banned_keys:
        out.pop(k, None)
    return out


class TreasureDeliveryService:
    """Deliver immutable transcription proposals to Treasure/Moten intake.

    Reuses MotenIntakeService patterns (outbox → HTTP POST /intake/{type})
    without creating a second review/release ledger in THREEZONE.
    """

    def __init__(
        self,
        outbox: TreasureDeliveryOutbox | None = None,
        *,
        propose_get: Callable[[str], TranscriptionProposal] | None = None,
        moten_service_url: str | None = None,
        moten_shared_secret: str | None = None,
        moten_timeout_seconds: float = 5.0,
        async_deliver: bool = False,
        http_post: Callable[..., tuple[int, Any]] | None = None,
    ) -> None:
        self.outbox = outbox or TreasureDeliveryOutbox(":memory:")
        self._propose_get = propose_get
        self.moten_service_url = (moten_service_url or "").rstrip("/")
        self.moten_shared_secret = moten_shared_secret or ""
        self.moten_timeout_seconds = float(moten_timeout_seconds or 5)
        self.async_deliver = bool(async_deliver)
        self._http_post = http_post

    @property
    def moten_enabled(self) -> bool:
        return bool(self.moten_service_url)

    def _resolve_proposal(self, proposal: TranscriptionProposal | str) -> TranscriptionProposal:
        if isinstance(proposal, TranscriptionProposal):
            return proposal
        if self._propose_get is None:
            raise ProposalNotFound(f"proposal not found: {proposal}")
        return self._propose_get(proposal)

    def build_payload(
        self,
        proposal: TranscriptionProposal | str,
        *,
        producer: dict[str, Any] | None = None,
        lineage: dict[str, Any] | None = None,
        job_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prop = self._resolve_proposal(proposal)
        return build_delivery_payload(
            prop, producer=producer, lineage=lineage, job_result=job_result
        )

    def deliver(
        self,
        proposal: TranscriptionProposal | str,
        *,
        producer: dict[str, Any] | None = None,
        lineage: dict[str, Any] | None = None,
        job_result: dict[str, Any] | None = None,
        force: bool = False,
        now: float | None = None,
        sync: bool | None = None,
    ) -> DeliveryReceipt:
        """Enqueue + (optionally) transport a proposal. Idempotent on intake_accepted.

        When Moten is disabled: records ``skipped`` (honest fail-closed) unless
        a prior ``intake_accepted`` receipt exists for the same content_hash.
        """
        prop = self._resolve_proposal(proposal)
        if not prop.content_hash:
            raise DeliveryError("proposal missing content_hash", code="missing_content_hash")
        if not prop.verify_hash():
            raise DeliveryError(
                "proposal content_hash does not match segments",
                code="content_hash_mismatch",
            )

        existing = self.outbox.latest_intake_accepted(prop.proposal_id, prop.content_hash)
        if existing is not None and not force:
            return existing

        ts = _now(now)
        payload = build_delivery_payload(
            prop,
            producer=producer,
            lineage=lineage,
            job_result=job_result,
            occurred_at=ts,
        )

        if not self.moten_enabled:
            receipt = DeliveryReceipt(
                delivery_id=_new_delivery_id(),
                proposal_id=prop.proposal_id,
                job_id=prop.job_id,
                content_hash=prop.content_hash,
                handoff_type=HANDOFF_TYPE,
                payload=payload,
                status=STATUS_SKIPPED,
                attempts=0,
                last_error="moten service not configured",
                created_at=ts,
                updated_at=ts,
            )
            return self.outbox.insert(receipt)

        receipt = DeliveryReceipt(
            delivery_id=_new_delivery_id(),
            proposal_id=prop.proposal_id,
            job_id=prop.job_id,
            content_hash=prop.content_hash,
            handoff_type=HANDOFF_TYPE,
            payload=payload,
            status=STATUS_QUEUED,
            attempts=0,
            created_at=ts,
            updated_at=ts,
        )
        self.outbox.insert(receipt)

        do_sync = (not self.async_deliver) if sync is None else bool(sync)
        if do_sync:
            return self._transport(receipt.delivery_id)
        thread = threading.Thread(
            target=self._transport, args=(receipt.delivery_id,), daemon=True
        )
        thread.start()
        return self.outbox.get(receipt.delivery_id) or receipt

    def _transport(self, delivery_id: str) -> DeliveryReceipt:
        row = self.outbox.get(delivery_id)
        if not row:
            raise DeliveryError(f"delivery not found: {delivery_id}", code="delivery_not_found")
        if row.status == STATUS_INTAKE_ACCEPTED:
            return row

        body = _dumps(row.payload).encode("utf-8")
        url = f"{self.moten_service_url}/intake/{HANDOFF_TYPE}"
        attempts = int(row.attempts or 0) + 1
        ts = _now()

        try:
            if self._http_post is not None:
                status_code, response_body = self._http_post(
                    url, body, self.moten_shared_secret, self.moten_timeout_seconds
                )
            else:
                status_code, response_body = self._default_http_post(
                    url, body, self.moten_shared_secret, self.moten_timeout_seconds
                )

            # Parse body if string
            parsed = response_body
            if isinstance(response_body, (bytes, bytearray)):
                parsed = response_body.decode("utf-8", errors="replace")
            if isinstance(parsed, str):
                parsed = _loads(parsed, parsed)

            projections = _extract_projections(parsed)
            meta = {
                "intake_accepted": True,
                "means": "intake_accepted_transport_only",
                "governance": "none",
                "http_status": status_code,
            }
            if isinstance(parsed, dict):
                # Prefer remote honesty flags; never promote bare accepted to governance.
                if parsed.get("intake_accepted") is True or parsed.get("status") == STATUS_INTAKE_ACCEPTED:
                    meta["intake_accepted"] = True
                # Strip governance misuse of bare accepted if present
                if "accepted" in parsed and "intake_accepted" not in parsed:
                    # Legacy alias only — record under metadata, not as status.
                    meta["legacy_accepted_alias"] = bool(parsed.get("accepted"))
                for k in ("intake_id", "audit_event_id", "message"):
                    if k in parsed:
                        meta[k] = parsed[k]

            row.status = STATUS_INTAKE_ACCEPTED
            row.attempts = attempts
            row.response_status = int(status_code) if status_code is not None else None
            row.response_body = parsed
            row.response_metadata = meta
            row.last_error = None
            row.updated_at = ts
            row.delivered_at = ts
            row.canonical_packet_id = projections.get("canonical_packet_id")
            row.canonical_revision_id = projections.get("canonical_revision_id")
            row.canonical_status = projections.get("canonical_status")
            # Keep payload flags honest
            row.payload = dict(row.payload or {})
            row.payload["publish"] = False
            row.payload["treasure_release"] = False
            row.payload["delivery_state"] = DELIVERY_STATE_INTAKE_ACCEPTED
            return self.outbox.update(row)

        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            row.status = STATUS_FAILED
            row.attempts = attempts
            row.response_status = exc.code
            row.response_body = _loads(detail, detail)
            row.last_error = f"http_{exc.code}"
            row.updated_at = ts
            return self.outbox.update(row)
        except Exception as exc:
            row.status = STATUS_FAILED
            row.attempts = attempts
            row.last_error = str(exc)
            row.updated_at = ts
            return self.outbox.update(row)

    @staticmethod
    def _default_http_post(
        url: str, body: bytes, shared_secret: str, timeout: float
    ) -> tuple[int, Any]:
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Moten-Shared-Secret": shared_secret or "",
                "X-Three-Zone-Source": "three-zone-api",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, _loads(raw, raw)

    def reconcile(
        self, proposal: TranscriptionProposal | str
    ) -> dict[str, Any]:
        """Compare local proposal vs last delivery receipt.

        Detects pending / queued / skipped / failed / intake_accepted / mismatch.
        Never invents ControlPlane or Path A review seats.
        """
        prop = self._resolve_proposal(proposal)
        latest = self.outbox.latest_for_proposal(prop.proposal_id)

        if latest is None:
            status = STATUS_PENDING
            delivery_state = DELIVERY_STATE_SUBMITTED
        elif latest.content_hash != prop.content_hash:
            # Immutable proposals should never diverge; flag mismatch if they do.
            status = STATUS_MISMATCH
            delivery_state = DELIVERY_STATE_MISMATCH
        else:
            status = latest.status
            delivery_state = _map_delivery_state(latest.status)

        receipt_dict = latest.to_dict() if latest else None
        # Scrub any accidental governance "accepted" from public reconcile view.
        if receipt_dict and isinstance(receipt_dict.get("response_body"), dict):
            # Keep legacy alias visible only under means — do not elevate.
            pass

        return {
            "proposal_id": prop.proposal_id,
            "job_id": prop.job_id,
            "content_hash": prop.content_hash,
            "proposal_status": prop.status,
            "reconcile_status": status,
            "delivery_state": delivery_state,
            "moten_enabled": self.moten_enabled,
            "publish": False,
            "treasure_release": False,
            "packet_family": PACKET_FAMILY,
            "packet_type": PACKET_TYPE,
            "intake_accepted": status == STATUS_INTAKE_ACCEPTED,
            "governance": "none",
            "means": "transport_receipt_only"
            if status == STATUS_INTAKE_ACCEPTED
            else "local_reconcile_only",
            "last_delivery": receipt_dict,
            "canonical_packet_id": latest.canonical_packet_id if latest else None,
            "canonical_revision_id": latest.canonical_revision_id if latest else None,
            "canonical_status": latest.canonical_status if latest else None,
            # Explicit: seats are NOT in THREEZONE
            "path_a_seats_in_threezone": False,
            "reviewer_1": None,
            "reviewer_2": None,
            "release_authority": None,
        }

    def status(self, delivery_id: str) -> DeliveryReceipt:
        row = self.outbox.get(delivery_id)
        if not row:
            raise DeliveryError(f"delivery not found: {delivery_id}", code="delivery_not_found")
        return row


_default_delivery: TreasureDeliveryService | None = None


def get_delivery_service(
    *,
    reload: bool = False,
    propose_get: Callable[[str], TranscriptionProposal] | None = None,
) -> TreasureDeliveryService:
    global _default_delivery
    if _default_delivery is None or reload:
        path = (
            os.environ.get("THREEZONE_TREASURE_DELIVERY_PATH")
            or os.environ.get("THREEZONE_AI_PROPOSALS_PATH")
            or "data/ai_proposals.sqlite"
        ).strip() or "data/ai_proposals.sqlite"
        # Share proposals sqlite file when path is shared; outbox uses own table.
        url = (os.environ.get("TZ_MOTEN_SERVICE_URL") or "").rstrip("/")
        secret = os.environ.get("TZ_MOTEN_SHARED_SECRET") or ""
        timeout = float(os.environ.get("TZ_MOTEN_TIMEOUT_SECONDS") or "5")
        if propose_get is None:
            from threezone_ai.proposals.service import get_propose_service

            propose_get = lambda pid: get_propose_service().get(pid)  # noqa: E731
        _default_delivery = TreasureDeliveryService(
            TreasureDeliveryOutbox(path),
            propose_get=propose_get,
            moten_service_url=url,
            moten_shared_secret=secret,
            moten_timeout_seconds=timeout,
            async_deliver=False,
        )
    return _default_delivery


def reset_delivery_service() -> None:
    global _default_delivery
    if _default_delivery is not None:
        try:
            _default_delivery.outbox.close()
        except Exception:
            pass
    _default_delivery = None
