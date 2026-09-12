"""Y6 — Treasure Path A review/revision status as read-only projections.

Seats (R1 / R2 / Release) stay in Treasure. THREEZONE mirrors status receipts
only: append-only revision projection records + canonical_* fields on delivery
outbox. Never a competing approval ledger; never treasure_release=true local
authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from threezone_ai.proposals.types import ProposalNotFound, TranscriptionProposal

# G0-C vocabulary projections (Y6 slice). Transport intake_accepted is NOT here.
CANONICAL_STATUSES = frozenset(
    {
        "admitted",
        "in_review",
        "changes_requested",
        "released",
        "rejected",
        "corrected",
        "superseded",
    }
)

# Explicitly never treat these as canonical governance status.
BANNED_CANONICAL_STATUSES = frozenset(
    {
        "accepted",  # bare accepted banned as governance
        "intake_accepted",  # transport only (Y5)
        "delivered",
        "received",
        "ingested",
        "queued",
        "pending",
        "skipped",
        "failed",
        "mismatch",
        "submitted",
        "queued_for_delivery",
    }
)

SEAT_FIELD_KEYS = frozenset(
    {
        "reviewer_1",
        "reviewer_2",
        "release_authority",
        "r1",
        "r2",
        "review_1_pending",
        "review_2_pending",
        "assigned_reviewer",
        "assigned_release",
        "seat_assignment",
        "approve",
        "approval",
        "approvals",
    }
)

PROJECTION_SCHEMA_REF = "threezone.treasure.revision.projection.v0"


class ProjectionError(Exception):
    status = 400
    code = "projection_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class ProjectionImmutable(ProjectionError):
    status = 409
    code = "projection_immutable"


class InvalidTreasureReceipt(ProjectionError):
    status = 400
    code = "invalid_treasure_receipt"


REVISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS treasure_revision_projections (
    projection_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    canonical_packet_id TEXT,
    canonical_revision_id TEXT,
    canonical_status TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trev_proposal
    ON treasure_revision_projections(proposal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_trev_status
    ON treasure_revision_projections(canonical_status, created_at);
CREATE INDEX IF NOT EXISTS idx_trev_packet
    ON treasure_revision_projections(canonical_packet_id, created_at);
"""


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


def _new_projection_id() -> str:
    return f"trp_{uuid.uuid4().hex[:16]}"


def receipt_hash_for(payload: dict[str, Any]) -> str:
    """Stable hash of the receipt payload used for projection lineage."""
    digest = hashlib.sha256(_dumps(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _scrub_seat_fields(obj: Any) -> Any:
    """Drop seat / approval assignment keys from nested receipt copies."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in SEAT_FIELD_KEYS:
                continue
            out[k] = _scrub_seat_fields(v)
        return out
    if isinstance(obj, list):
        return [_scrub_seat_fields(x) for x in obj]
    return obj


def validate_treasure_receipt(receipt: Any) -> dict[str, Any]:
    """Validate Treasure status receipt shape for projection ingest.

    Required: canonical_status in G0-C projection vocabulary.
    Optional: canonical_packet_id, canonical_revision_id, and opaque extras.
    Rejects bare accepted / intake_accepted as canonical_status.
    Strips seat assignment fields; never treats them as local authority.
    """
    if not isinstance(receipt, dict):
        raise InvalidTreasureReceipt("receipt must be a JSON object", code="receipt_not_object")

    status = receipt.get("canonical_status")
    if status is None and isinstance(receipt.get("status"), str):
        # Allow alias key "status" only when it is a projection vocabulary value.
        alias = receipt.get("status")
        if alias in CANONICAL_STATUSES:
            status = alias
        elif alias in BANNED_CANONICAL_STATUSES:
            raise InvalidTreasureReceipt(
                f"canonical_status {alias!r} is transport/governance-banned; "
                f"use one of: {sorted(CANONICAL_STATUSES)}",
                code="banned_canonical_status",
            )

    if not isinstance(status, str) or not status.strip():
        raise InvalidTreasureReceipt(
            "receipt requires canonical_status",
            code="missing_canonical_status",
        )
    status = status.strip()

    if status in BANNED_CANONICAL_STATUSES or status == "accepted":
        raise InvalidTreasureReceipt(
            f"canonical_status {status!r} is not a Treasure Path A projection "
            f"(intake_accepted ≠ released; bare accepted banned)",
            code="banned_canonical_status",
        )
    if status not in CANONICAL_STATUSES:
        raise InvalidTreasureReceipt(
            f"canonical_status {status!r} not in projection vocabulary "
            f"{sorted(CANONICAL_STATUSES)}",
            code="unknown_canonical_status",
        )

    # Reject explicit seat-assignment *actions* (not mere null projections).
    for key in ("assign_reviewer", "assign_release", "approve_action", "seat_action"):
        if receipt.get(key):
            raise InvalidTreasureReceipt(
                f"receipt must not include seat action {key!r}; seats stay in Treasure",
                code="seat_action_forbidden",
            )

    cleaned = _scrub_seat_fields(dict(receipt))
    cleaned["canonical_status"] = status
    # Honesty markers — projection only; local release authority stays false.
    cleaned["treasure_release"] = False
    cleaned["projection_only"] = True
    cleaned["governance"] = "treasure_path_a_projection"
    cleaned["means"] = "read_only_status_projection"
    cleaned["path_a_seats_in_threezone"] = False

    packet_id = cleaned.get("canonical_packet_id")
    revision_id = cleaned.get("canonical_revision_id")
    if packet_id is not None and not isinstance(packet_id, str):
        raise InvalidTreasureReceipt(
            "canonical_packet_id must be a string when present",
            code="bad_packet_id",
        )
    if revision_id is not None and not isinstance(revision_id, str):
        raise InvalidTreasureReceipt(
            "canonical_revision_id must be a string when present",
            code="bad_revision_id",
        )

    return cleaned


@dataclass
class RevisionProjection:
    """Append-only read-only projection of a Treasure revision/status receipt."""

    projection_id: str
    proposal_id: str
    canonical_packet_id: str | None
    canonical_revision_id: str | None
    canonical_status: str
    receipt_hash: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "proposal_id": self.proposal_id,
            "canonical_packet_id": self.canonical_packet_id,
            "canonical_revision_id": self.canonical_revision_id,
            "canonical_status": self.canonical_status,
            "receipt_hash": self.receipt_hash,
            "payload": dict(self.payload or {}),
            "created_at": self.created_at,
            "schema_ref": PROJECTION_SCHEMA_REF,
            # Explicit honesty
            "treasure_release": False,
            "projection_only": True,
            "local_release_authority": False,
            "path_a_seats_in_threezone": False,
            "governance": "treasure_path_a_projection",
            "means": "read_only_status_projection",
            "reviewer_1": None,
            "reviewer_2": None,
            "release_authority": None,
        }


def _row_to_projection(row: sqlite3.Row) -> RevisionProjection:
    return RevisionProjection(
        projection_id=row["projection_id"],
        proposal_id=row["proposal_id"],
        canonical_packet_id=row["canonical_packet_id"],
        canonical_revision_id=row["canonical_revision_id"],
        canonical_status=row["canonical_status"],
        receipt_hash=row["receipt_hash"],
        payload=_loads(row["payload_json"], {}) or {},
        created_at=float(row["created_at"] or 0),
    )


class TreasureRevisionProjectionStore:
    """Append-only SQLite store for Treasure revision status projections."""

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
            self._conn.executescript(REVISION_SCHEMA)
            self._conn.commit()

    def insert(self, row: RevisionProjection) -> RevisionProjection:
        with self._lock:
            self._conn.execute(
                "INSERT INTO treasure_revision_projections("
                "projection_id, proposal_id, canonical_packet_id, canonical_revision_id,"
                " canonical_status, receipt_hash, payload_json, created_at"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    row.projection_id,
                    row.proposal_id,
                    row.canonical_packet_id,
                    row.canonical_revision_id,
                    row.canonical_status,
                    row.receipt_hash,
                    _dumps(row.payload),
                    row.created_at,
                ),
            )
            self._conn.commit()
        return row

    def get(self, projection_id: str) -> RevisionProjection | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM treasure_revision_projections WHERE projection_id=?",
                (projection_id,),
            ).fetchone()
        return _row_to_projection(row) if row else None

    def latest_for_proposal(self, proposal_id: str) -> RevisionProjection | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM treasure_revision_projections WHERE proposal_id=?"
                " ORDER BY created_at DESC, projection_id DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        return _row_to_projection(row) if row else None

    def list_for_proposal(self, proposal_id: str) -> list[RevisionProjection]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM treasure_revision_projections WHERE proposal_id=?"
                " ORDER BY created_at ASC, projection_id ASC",
                (proposal_id,),
            ).fetchall()
        return [_row_to_projection(r) for r in rows]

    def update(self, projection_id: str, **_fields: Any) -> None:
        """Mutating projection rows is forbidden — always raises."""
        raise ProjectionImmutable(
            f"revision projection {projection_id} is append-only; mutate rejected"
        )

    def delete(self, projection_id: str) -> None:
        raise ProjectionImmutable(
            f"revision projection {projection_id} is append-only; delete rejected"
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class TreasureProjectionService:
    """Apply Treasure status receipts → append-only projections + canonical_* mirror."""

    def __init__(
        self,
        store: TreasureRevisionProjectionStore | None = None,
        *,
        propose_get: Callable[[str], TranscriptionProposal] | None = None,
        delivery_outbox: Any | None = None,
    ) -> None:
        self.store = store or TreasureRevisionProjectionStore(":memory:")
        self._propose_get = propose_get
        self.delivery_outbox = delivery_outbox

    def _resolve_proposal(self, proposal_id: str) -> TranscriptionProposal | None:
        if self._propose_get is None:
            return None
        return self._propose_get(proposal_id)

    def apply_treasure_receipt(
        self,
        proposal_id: str,
        receipt: dict[str, Any] | Any,
        *,
        now: float | None = None,
        require_proposal: bool = True,
    ) -> RevisionProjection:
        """Validate receipt, append immutable revision projection, update canonical_*.

        Documented as **receipt ingest** (webhook/mock) — not a seat / approve action.
        """
        if not proposal_id or not isinstance(proposal_id, str):
            raise InvalidTreasureReceipt("proposal_id required", code="missing_proposal_id")

        if require_proposal and self._propose_get is not None:
            prop = self._resolve_proposal(proposal_id)
            if prop is None:
                raise ProposalNotFound(f"proposal not found: {proposal_id}")

        cleaned = validate_treasure_receipt(receipt)
        ts = _now(now)
        rhash = receipt_hash_for(cleaned)
        row = RevisionProjection(
            projection_id=_new_projection_id(),
            proposal_id=proposal_id,
            canonical_packet_id=cleaned.get("canonical_packet_id"),
            canonical_revision_id=cleaned.get("canonical_revision_id"),
            canonical_status=cleaned["canonical_status"],
            receipt_hash=rhash,
            payload=cleaned,
            created_at=ts,
        )
        self.store.insert(row)
        self._mirror_canonical_to_delivery(proposal_id, row)
        return row

    def _mirror_canonical_to_delivery(
        self, proposal_id: str, row: RevisionProjection
    ) -> None:
        """Update delivery outbox canonical_* projection fields when available."""
        outbox = self.delivery_outbox
        if outbox is None:
            return
        latest = None
        try:
            latest = outbox.latest_for_proposal(proposal_id)
        except Exception:
            return
        if latest is None:
            return
        latest.canonical_packet_id = row.canonical_packet_id
        latest.canonical_revision_id = row.canonical_revision_id
        latest.canonical_status = row.canonical_status
        # Never flip local release authority.
        if hasattr(latest, "payload") and isinstance(latest.payload, dict):
            latest.payload = dict(latest.payload)
            latest.payload["treasure_release"] = False
            latest.payload["canonical_packet_id"] = row.canonical_packet_id
            latest.payload["canonical_revision_id"] = row.canonical_revision_id
            latest.payload["canonical_status"] = row.canonical_status
            latest.payload["projection_only"] = True
        latest.updated_at = _now()
        try:
            outbox.update(latest)
        except Exception:
            pass

    def latest(self, proposal_id: str) -> RevisionProjection | None:
        return self.store.latest_for_proposal(proposal_id)

    def list_revisions(self, proposal_id: str) -> list[RevisionProjection]:
        return self.store.list_for_proposal(proposal_id)

    def get_projection(self, projection_id: str) -> RevisionProjection:
        row = self.store.get(projection_id)
        if row is None:
            raise ProjectionError(
                f"projection not found: {projection_id}", code="projection_not_found"
            )
        return row

    def mutate_projection(self, projection_id: str, **fields: Any) -> None:
        """Always rejected — append-only."""
        self.store.update(projection_id, **fields)

    def projection_summary(self, proposal_id: str) -> dict[str, Any]:
        """Operator view: latest projection + revision list (read-only)."""
        latest = self.latest(proposal_id)
        revisions = self.list_revisions(proposal_id)
        return {
            "proposal_id": proposal_id,
            "schema_ref": PROJECTION_SCHEMA_REF,
            "latest": latest.to_dict() if latest else None,
            "revisions": [r.to_dict() for r in revisions],
            "revision_count": len(revisions),
            "canonical_packet_id": latest.canonical_packet_id if latest else None,
            "canonical_revision_id": latest.canonical_revision_id if latest else None,
            "canonical_status": latest.canonical_status if latest else None,
            "treasure_release": False,
            "local_release_authority": False,
            "projection_only": True,
            "path_a_seats_in_threezone": False,
            "governance": "treasure_path_a_projection",
            "means": "read_only_status_projection",
            "note": "Seats stay in Treasure; THREEZONE mirrors status receipts only",
            "allowed_statuses": sorted(CANONICAL_STATUSES),
            "reviewer_1": None,
            "reviewer_2": None,
            "release_authority": None,
        }


_default_projections: TreasureProjectionService | None = None


def get_projection_service(
    *,
    reload: bool = False,
    propose_get: Callable[[str], TranscriptionProposal] | None = None,
    delivery_outbox: Any | None = None,
) -> TreasureProjectionService:
    global _default_projections
    if _default_projections is None or reload:
        path = (
            os.environ.get("THREEZONE_TREASURE_DELIVERY_PATH")
            or os.environ.get("THREEZONE_AI_PROPOSALS_PATH")
            or "data/ai_proposals.sqlite"
        ).strip() or "data/ai_proposals.sqlite"
        if propose_get is None:
            from threezone_ai.proposals.service import get_propose_service

            propose_get = lambda pid: get_propose_service().get(pid)  # noqa: E731
        if delivery_outbox is None:
            try:
                from threezone_ai.proposals.delivery import get_delivery_service

                delivery_outbox = get_delivery_service(propose_get=propose_get).outbox
            except Exception:
                delivery_outbox = None
        _default_projections = TreasureProjectionService(
            TreasureRevisionProjectionStore(path),
            propose_get=propose_get,
            delivery_outbox=delivery_outbox,
        )
    elif propose_get is not None:
        _default_projections._propose_get = propose_get
    if delivery_outbox is not None and _default_projections is not None:
        _default_projections.delivery_outbox = delivery_outbox
    return _default_projections


def reset_projection_service() -> None:
    global _default_projections
    if _default_projections is not None:
        try:
            _default_projections.store.close()
        except Exception:
            pass
    _default_projections = None
