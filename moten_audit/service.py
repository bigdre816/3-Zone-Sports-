"""Canonical audit, Treasure verification, and governed publication services."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import Config
from .db import Database, dumps, loads

AUDIT_SCHEMA = "moten.audit.event.v1"
VERIFY_SCHEMA = "treasure.network.verification.v1"
POLICIES: dict[str, dict[str, Any]] = {
    "research.question.created": {"requirement": "PERMITTED", "mode": "SUMMARY_AUDIT", "profile": "RESEARCH_VERIFICATION"},
    "research.question.version.committed": {"requirement": "PERMITTED", "mode": "SUMMARY_AUDIT", "profile": "RESEARCH_VERIFICATION"},
    "research.observation.recorded": {"requirement": "PERMITTED", "mode": "HASH_ONLY", "profile": "RESEARCH_VERIFICATION"},
    "rights.revoked": {"requirement": "REQUIRED", "mode": "SUMMARY_AUDIT", "profile": "RIGHTS_VERIFICATION"},
    "rights.version.created": {"requirement": "REQUIRED", "mode": "SUMMARY_AUDIT", "profile": "RIGHTS_VERIFICATION"},
    "rights.version.superseded": {"requirement": "REQUIRED", "mode": "SUMMARY_AUDIT", "profile": "RIGHTS_VERIFICATION"},
    "measurement.fact.frozen": {"requirement": "PERMITTED", "mode": "HASH_ONLY", "profile": "MEASUREMENT_VERIFICATION"},
    "measurement.fact.corrected": {"requirement": "REQUIRED", "mode": "HASH_ONLY", "profile": "MEASUREMENT_VERIFICATION"},
    "settlement.calculated": {"requirement": "REQUIRED", "mode": "SUMMARY_AUDIT", "profile": "SETTLEMENT_VERIFICATION"},
    "settlement.closed": {"requirement": "REQUIRED", "mode": "SUMMARY_AUDIT", "profile": "SETTLEMENT_VERIFICATION"},
    "settlement.correction.recorded": {"requirement": "REQUIRED", "mode": "SUMMARY_AUDIT", "profile": "SETTLEMENT_VERIFICATION"},
    "evidence.manifest.created": {"requirement": "PERMITTED", "mode": "HASH_ONLY", "profile": "EVIDENCE_VERIFICATION"},
    "evidence.package.sealed": {"requirement": "REQUIRED", "mode": "HASH_ONLY", "profile": "EVIDENCE_VERIFICATION"},
    "policy.decision": {"requirement": "PERMITTED", "mode": "SUMMARY_AUDIT", "profile": "RUNTIME_VERIFICATION"},
    "socket.admission": {"requirement": "PERMITTED", "mode": "HASH_ONLY", "profile": "RUNTIME_VERIFICATION"},
    "socket.denied": {"requirement": "PERMITTED", "mode": "HASH_ONLY", "profile": "RUNTIME_VERIFICATION"},
    "invention.created": {"requirement": "PERMITTED", "mode": "SUMMARY_AUDIT", "profile": "INVENTION_VERIFICATION"},
    "invention.version.committed": {"requirement": "PERMITTED", "mode": "SUMMARY_AUDIT", "profile": "INVENTION_VERIFICATION"},
    "human.contribution.recorded": {"requirement": "PERMITTED", "mode": "HASH_ONLY", "profile": "INVENTION_VERIFICATION"},
    "ai.assistance.recorded": {"requirement": "PROHIBITED", "mode": "HASH_ONLY", "profile": "INVENTION_VERIFICATION"},
}
SECRET_PATTERN = re.compile(r"(?:secret|seed|passphrase|private[_ -]?key|moten_xrpl_secret)", re.I)
ALLOWED_ORGANIZATIONS = {
    "MOTEN_IP", "THREE_ZONE_KC", "TREASURE_NETWORK", "TREASURE_KC", "TREASURE_STL",
    "TREASURE_417", "TREASURE_HIGHLAND", "TREASURE_LAWRENCE", "TREASURE_COLUMBIA",
    "WEALTH_PASSPORT",
}


def timestamp(value: Any | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str):
        raise ValueError("timestamps must be ISO-8601 strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonicalize(value: Any) -> bytes:
    """Stable UTF-8 JSON: sorted keys, fixed separators, explicit null values."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_canonical_audit_event(event: dict) -> str:
    body = {key: value for key, value in event.items() if key != "canonical_event_hash"}
    return sha256(canonicalize(body))


def _contains_secret(value: Any, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            candidate = f"{path}.{key}" if path else str(key)
            if SECRET_PATTERN.search(str(key)):
                return candidate
            found = _contains_secret(child, candidate)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _contains_secret(child, f"{path}[{index}]")
            if found:
                return found
    return None


class AuditService:
    def __init__(self, db: Database, config: Config):
        self.db, self.config = db, config
        self._ensure_profile()
        self._seed_policies()

    def _ensure_profile(self) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO signing_profiles VALUES (?,?,?,?,?,?,?)",
            (self.config.signing_profile_id, "Andre / Moten authorized signer",
             self.config.xrpl_account or None, self.config.xrpl_network,
             "CONFIGURED" if self.config.is_simulation or self.config.xrpl_account else "NOT_CONFIGURED", timestamp(), "IP Steward"),
        )

    def _seed_policies(self) -> None:
        for event_type, policy in POLICIES.items():
            self.db.execute(
                "INSERT OR IGNORE INTO event_policies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (event_type, "v1", policy["requirement"], policy["mode"], dumps([]), dumps(["secret", "seed", "passphrase", "private_key"]),
                 "CONFIDENTIAL_HASH_ONLY" if policy["mode"] == "HASH_ONLY" else "INTERNAL_AUDIT", 0,
                 dumps([self.config.signing_profile_id]), timestamp(), None),
            )

    def policy(self, event_type: str) -> dict | None:
        row = self.db.one("SELECT * FROM event_policies WHERE event_type=? AND active_until IS NULL", (event_type,))
        return dict(row) if row else None

    def create_event(self, supplied: dict) -> dict:
        required = ["event_id", "event_type", "organization_id", "source_system", "object_id", "object_version",
                    "occurred_at", "actor_type", "actor_id", "actor_role", "action"]
        missing = [field for field in required if not supplied.get(field)]
        if missing:
            raise ValueError("missing required fields: " + ", ".join(missing))
        policy = self.policy(supplied["event_type"])
        if not policy:
            raise ValueError("unknown event schema/event type; event is held")
        event = dict(supplied)
        event.update({
            "schema": AUDIT_SCHEMA, "schema_version": "v1", "recorded_at": timestamp(supplied.get("recorded_at")),
            "department": supplied.get("department", "MOTEN_ON_CHAIN_AUDIT"),
            "project_family": supplied.get("project_family", "Moten"),
            "object_type": supplied.get("object_type", "record"), "decision": supplied.get("decision"),
            "reason_code": supplied.get("reason_code"), "previous_event_id": supplied.get("previous_event_id"),
            "previous_event_hash": supplied.get("previous_event_hash"), "correlation_id": supplied.get("correlation_id") or str(uuid.uuid4()),
            "causation_id": supplied.get("causation_id"), "environment": supplied.get("environment", self.config.env),
            "payload": supplied.get("payload", {}), "classification": supplied.get("classification", policy["classification"]),
            "on_chain_policy": supplied.get("on_chain_policy", policy["publication_requirement"]),
            "legal_effect": supplied.get("legal_effect", "audit_evidence_only"), "created_by": supplied.get("created_by", supplied["actor_id"]),
            "human_approval_id": supplied.get("human_approval_id"), "signature_profile_id": supplied.get("signature_profile_id"),
        })
        event["occurred_at"] = timestamp(event["occurred_at"])
        event["payload_hash"] = sha256(canonicalize(event["payload"]))
        secret_path = _contains_secret(event["payload"])
        if secret_path:
            event["classification"] = "CREDENTIAL"
            event["on_chain_policy"] = "HOLD_FOR_REVIEW"
            event["security_hold_reason"] = "sensitive field blocked"
        if event["previous_event_id"]:
            previous = self.db.one("SELECT canonical_event_hash FROM audit_events WHERE event_id=?", (event["previous_event_id"],))
            if not previous or previous["canonical_event_hash"] != event["previous_event_hash"]:
                raise ValueError("invalid event lineage; event is held")
        event["canonical_event_hash"] = hash_canonical_audit_event(event)
        if self.db.one("SELECT 1 FROM audit_events WHERE event_id=?", (event["event_id"],)):
            raise ValueError("event_id is immutable and already exists")
        self.db.execute(
            "INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event["event_id"], event["event_type"], "v1", event["organization_id"], event["source_system"], event["object_id"],
             event["object_version"], event["occurred_at"], event["recorded_at"], event["canonical_event_hash"], event["previous_event_id"],
             event["previous_event_hash"], event["classification"], event["on_chain_policy"], event["legal_effect"], dumps(event), timestamp()),
        )
        self.db.execute("INSERT INTO audit_event_versions VALUES (?,?,?,?,?)",
                        (event["event_id"], 1, event["canonical_event_hash"], dumps(event), timestamp()))
        self.db.execute("INSERT INTO audit_event_lineage VALUES (?,?,?,?)",
                        (event["event_id"], event["previous_event_id"], event["previous_event_hash"], timestamp()))
        return event

    def get_event(self, event_id: str) -> dict | None:
        row = self.db.one("SELECT event_json FROM audit_events WHERE event_id=?", (event_id,))
        return loads(row["event_json"]) if row else None

    def list_events(self) -> list[dict]:
        return [loads(row["event_json"]) for row in self.db.many("SELECT event_json FROM audit_events ORDER BY created_at DESC")]

    def verify(self, event_id: str) -> dict:
        event = self.get_event(event_id)
        if not event:
            raise ValueError("event not found")
        verification_id = f"TNV-{uuid.uuid4().hex[:12].upper()}"
        checks: list[dict] = []
        def check(name: str, ok: bool, reason: str = ""):
            checks.append({"name": name, "status": "PASSED" if ok else "FAILED", "reason": reason})
        check("SOURCE_IDENTITY", event["organization_id"] in ALLOWED_ORGANIZATIONS, "organization not registered")
        check("SOURCE_AUTHORITY", bool(event["actor_id"] and event["actor_role"]))
        check("SCHEMA", event["schema"] == AUDIT_SCHEMA and bool(self.policy(event["event_type"])), "unknown schema/event type")
        check("HASH_INTEGRITY", hash_canonical_audit_event(event) == event["canonical_event_hash"], "canonical hash mismatch")
        check("TIMESTAMP", bool(event["occurred_at"] and event["recorded_at"]))
        check("LINEAGE", not event["previous_event_id"] or bool(self.db.one("SELECT 1 FROM audit_events WHERE event_id=?", (event["previous_event_id"],))), "prior event missing")
        check("DUPLICATE", not bool(self.db.one("SELECT 1 FROM verification_records WHERE source_event_id=? AND verification_status='VERIFIED'", (event_id,))), "already verified")
        secret_path = _contains_secret(event["payload"])
        check("CLASSIFICATION", not secret_path, "sensitive payload field blocked")
        policy = self.policy(event["event_type"])
        check("POLICY", event["on_chain_policy"] != "HOLD_FOR_REVIEW" and policy["publication_requirement"] != "PROHIBITED", "policy hold or prohibited")
        profile = POLICIES[event["event_type"]]["profile"] if event["event_type"] in POLICIES else "CITY_ENTITY_VERIFICATION"
        failed = [item for item in checks if item["status"] == "FAILED"]
        status = "HELD" if failed else "VERIFIED"
        eligible = status == "VERIFIED" and policy["publication_requirement"] != "PROHIBITED"
        envelope = {
            "schema": VERIFY_SCHEMA, "verification_id": verification_id, "verification_version": "v1",
            "source_organization_id": event["organization_id"], "source_system": event["source_system"],
            "source_event_id": event["event_id"], "source_event_type": event["event_type"], "source_object_id": event["object_id"],
            "source_object_version": event["object_version"], "source_event_hash": event["canonical_event_hash"],
            "source_previous_event_hash": event["previous_event_hash"], "source_recorded_at": event["recorded_at"],
            "received_at": timestamp(), "verified_at": timestamp() if eligible else None, "verification_status": status,
            "verification_profile": profile, "verification_checks": checks, "verification_evidence": [],
            "verification_evidence_hash": sha256(canonicalize([])), "policy_version": "v1",
            "network_actor_id": "TREASURE_NETWORK_SIMULATOR", "network_actor_role": "verification_infrastructure",
            "correlation_id": event["correlation_id"], "eligible_for_onchain": eligible,
            "hold_reason": failed[0]["reason"] if failed else None, "legal_effect": "verification_evidence_only",
        }
        envelope["canonical_verification_hash"] = sha256(canonicalize(envelope))
        self.db.execute("INSERT INTO verification_records VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (verification_id, event_id, status, profile, int(eligible), envelope["canonical_verification_hash"], dumps(envelope),
                         envelope["received_at"], envelope["verified_at"], envelope["hold_reason"]))
        for lifecycle in ["verification.received", "verification.started"] + [
            "verification.check.passed" if item["status"] == "PASSED" else "verification.check.failed" for item in checks
        ] + ["verification.completed" if eligible else "verification.held"]:
            self.db.execute("INSERT INTO verification_history(verification_id,event_type,detail,occurred_at) VALUES (?,?,?,?)",
                            (verification_id, lifecycle, dumps({"simulated": True}), timestamp()))
        return envelope

    def get_verification(self, verification_id: str) -> dict | None:
        row = self.db.one("SELECT envelope_json FROM verification_records WHERE verification_id=?", (verification_id,))
        return loads(row["envelope_json"]) if row else None

    def request_publication(self, event_id: str, verification_id: str, actor_role: str = "IP Steward") -> dict:
        if actor_role == "AI gateway":
            raise PermissionError("AI role cannot change publication state")
        event, verification = self.get_event(event_id), self.get_verification(verification_id)
        if not event or not verification or verification["source_event_id"] != event_id:
            raise ValueError("verified event and verification receipt are required")
        if verification["verification_status"] != "VERIFIED" or not verification["eligible_for_onchain"]:
            raise ValueError("unverified information cannot become a verified on-chain audit event")
        policy = self.policy(event["event_type"])
        if not policy or policy["publication_requirement"] == "PROHIBITED":
            raise ValueError("publication prohibited by policy")
        key = sha256(f"{event['canonical_event_hash']}|{self.config.xrpl_network}|{self.config.signing_profile_id}".encode())
        existing = self.db.one("SELECT * FROM blockchain_publication_requests WHERE idempotency_key=?", (key,))
        if existing:
            return dict(existing)
        mode = policy["publication_mode"]
        representation = self._representation(event, verification, mode)
        request_id = f"PUB-{uuid.uuid4().hex[:12].upper()}"
        self.db.execute("INSERT INTO blockchain_publication_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (request_id, event_id, verification_id, key, "QUEUED", mode, self.config.signing_profile_id, self.config.xrpl_network,
                         dumps(representation), None, timestamp(), timestamp()))
        return dict(self.db.one("SELECT * FROM blockchain_publication_requests WHERE request_id=?", (request_id,)))

    def _representation(self, event: dict, verification: dict, mode: str) -> dict:
        base = {key: event.get(key) for key in ("event_id", "event_type", "organization_id", "project_family", "object_type", "object_id",
                "object_version", "action", "decision", "reason_code", "previous_event_hash", "occurred_at", "legal_effect", "classification")}
        base.update({"moten_marker": "MOTEN_AUDIT_V1", "schema": AUDIT_SCHEMA, "canonical_event_hash": event["canonical_event_hash"],
                     "treasure_network_verification_hash": verification["canonical_verification_hash"], "audit_sequence": event["event_id"],
                     "publication_mode": mode})
        if mode == "FULL_AUDIT" and event["classification"] == "PUBLIC_AUDIT":
            base["payload"] = event["payload"]
        return base

    def publish(self, request_id: str) -> dict:
        request = self.db.one("SELECT * FROM blockchain_publication_requests WHERE request_id=?", (request_id,))
        if not request:
            raise ValueError("publication request not found")
        if request["status"] == "VALIDATED":
            return dict(request)
        profile = self.db.one("SELECT * FROM signing_profiles WHERE signing_profile_id=?", (request["signing_profile_id"],))
        if not profile or profile["status"] == "NOT_CONFIGURED":
            self.db.execute("UPDATE blockchain_publication_requests SET status='HELD',hold_reason=?,updated_at=? WHERE request_id=?",
                            ("unknown signing authority", timestamp(), request_id))
            return dict(self.db.one("SELECT * FROM blockchain_publication_requests WHERE request_id=?", (request_id,)))
        attempt_id = f"ATT-{uuid.uuid4().hex[:12].upper()}"
        self.db.execute("INSERT INTO blockchain_publication_attempts VALUES (?,?,?,?,?,?,?,?,?)",
                        (attempt_id, request_id, "SIGNING", None, None, None, None, None, dumps({"signer": profile["signing_profile_id"]})))
        self.db.execute("INSERT INTO signing_authority_events(event_type,profile_id,detail,occurred_at) VALUES (?,?,?,?)",
                        ("signing.requested", profile["signing_profile_id"], dumps({"request_id": request_id}), timestamp()))
        if not self.config.is_simulation:
            failure, result = "SIGNER_FAILURE", "testnet client not configured in this deployment"
            self.db.execute("UPDATE blockchain_publication_attempts SET status='HELD',failure_class=?,result_code=?,detail=? WHERE attempt_id=?",
                            (failure, result, dumps({"message": result}), attempt_id))
            self.db.execute("UPDATE blockchain_publication_requests SET status='HELD',hold_reason=?,updated_at=? WHERE request_id=?",
                            (result, timestamp(), request_id))
            return dict(self.db.one("SELECT * FROM blockchain_publication_requests WHERE request_id=?", (request_id,)))
        # Simulator creates no XRPL transaction ID and cannot be mistaken for XRPL evidence.
        now = timestamp()
        event = self.get_event(request["event_id"])
        self.db.execute("UPDATE blockchain_publication_attempts SET status='SIMULATED',result_code=?,submitted_at=?,validated_at=?,detail=? WHERE attempt_id=?",
                        ("SIMULATION_NO_XRPL_PUBLICATION", now, now, dumps({"simulation": True}), attempt_id))
        receipt_id = f"SIM-RECEIPT-{uuid.uuid4().hex[:12].upper()}"
        self.db.execute("INSERT INTO blockchain_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (receipt_id, event["event_id"], attempt_id, "simulation", profile["account"], None, None, "SIMULATED_AUDIT",
                         now, now, "SIMULATION_NO_XRPL_PUBLICATION", None, event["canonical_event_hash"],
                         sha256(request["approved_representation"].encode()), "local simulator", "SIMULATED"))
        self.db.execute("UPDATE blockchain_publication_requests SET status='SIMULATED',updated_at=? WHERE request_id=?", (now, request_id))
        self.db.execute("INSERT INTO signing_authority_events(event_type,profile_id,detail,occurred_at) VALUES (?,?,?,?)",
                        ("signing.completed", profile["signing_profile_id"], dumps({"request_id": request_id, "simulation": True}), now))
        self.db.execute("INSERT INTO verification_history(verification_id,event_type,detail,occurred_at) VALUES (?,?,?,?)",
                        (request["verification_id"], "blockchain.receipt.received", dumps({"receipt_id": receipt_id, "simulation": True}), now))
        return dict(self.db.one("SELECT * FROM blockchain_publication_requests WHERE request_id=?", (request_id,)))

    def receipts(self, event_id: str) -> list[dict]:
        return [dict(row) for row in self.db.many("SELECT * FROM blockchain_receipts WHERE event_id=? ORDER BY submitted_at DESC", (event_id,))]

    def list_requests(self) -> list[dict]:
        return [dict(row) for row in self.db.many("SELECT * FROM blockchain_publication_requests ORDER BY created_at DESC")]

    def publication(self, request_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM blockchain_publication_requests WHERE request_id=?", (request_id,))
        return dict(row) if row else None

    def hold_publication(self, request_id: str, actor_role: str) -> dict:
        if actor_role == "AI gateway":
            raise PermissionError("AI role cannot release or change a policy hold")
        if not self.publication(request_id):
            raise ValueError("publication request not found")
        self.db.execute("UPDATE blockchain_publication_requests SET status='HELD',hold_reason=?,updated_at=? WHERE request_id=?",
                        ("human hold", timestamp(), request_id))
        return self.publication(request_id)

    def signing_profile(self) -> dict:
        row = self.db.one("SELECT signing_profile_id,display_name,account,network,status,effective_at,signer_role"
                          " FROM signing_profiles WHERE signing_profile_id=?", (self.config.signing_profile_id,))
        return dict(row) if row else {"signing_profile_id": self.config.signing_profile_id, "status": "NOT_CONFIGURED"}

    def reconcile(self) -> dict:
        run_id, findings = f"REC-{uuid.uuid4().hex[:12].upper()}", []
        self.db.execute("INSERT INTO reconciliation_runs VALUES (?,?,?,?)", (run_id, "RUNNING", timestamp(), None))
        for row in self.db.many("SELECT r.* FROM blockchain_publication_requests r LEFT JOIN blockchain_receipts b ON r.event_id=b.event_id WHERE r.status='VALIDATED' AND b.receipt_id IS NULL"):
            findings.append(("BLOCKING DIFFERENCE", "missing_receipt", f"validated request {row['request_id']} has no receipt"))
        for severity, kind, detail in findings:
            self.db.execute("INSERT INTO reconciliation_findings(run_id,severity,finding_type,detail) VALUES (?,?,?,?)", (run_id, severity, kind, detail))
        status = "CLEAN" if not findings else ("BLOCKING DIFFERENCE" if any(x[0] == "BLOCKING DIFFERENCE" for x in findings) else "WARNING")
        self.db.execute("UPDATE reconciliation_runs SET status=?,completed_at=? WHERE run_id=?", (status, timestamp(), run_id))
        return {"run_id": run_id, "status": status, "findings": [{"severity": x[0], "type": x[1], "detail": x[2]} for x in findings]}

    def health(self) -> dict:
        queued = self.db.one("SELECT COUNT(*) AS count FROM blockchain_publication_requests WHERE status IN ('QUEUED','HELD')")["count"]
        profile = self.db.one("SELECT * FROM signing_profiles WHERE signing_profile_id=?", (self.config.signing_profile_id,))
        status = "HEALTHY" if self.config.is_simulation else "DEGRADED"
        if not profile or profile["status"] == "NOT_CONFIGURED":
            status = "BLOCKED"
        return {"status": status, "xrpl": "SIMULATION · NO XRPL PUBLICATION" if self.config.is_simulation else "TESTNET CONFIGURATION PENDING",
                "treasure": "SIMULATED TREASURE NETWORK VERIFICATION", "queue_depth": queued,
                "signing_profile": {"id": self.config.signing_profile_id, "status": profile["status"] if profile else "NOT_CONFIGURED"}}


class TreasureNetworkVerificationProvider:
    """Integration contract. Source applications never call a publisher directly."""
    def submitForVerification(self, event_id: str) -> dict: raise NotImplementedError
    def getVerification(self, verification_id: str) -> dict | None: raise NotImplementedError
    def getVerificationReceipt(self, verification_id: str) -> dict | None: raise NotImplementedError
    def checkVerificationStatus(self, verification_id: str) -> str | None: raise NotImplementedError
    def validateReceipt(self, verification_id: str) -> bool: raise NotImplementedError


class LocalTreasureNetworkVerificationSimulator(TreasureNetworkVerificationProvider):
    """Explicit local-only simulation, never a claim of network verification."""
    def __init__(self, service: AuditService): self.service = service
    def submitForVerification(self, event_id: str) -> dict: return self.service.verify(event_id)
    def getVerification(self, verification_id: str) -> dict | None: return self.service.get_verification(verification_id)
    def getVerificationReceipt(self, verification_id: str) -> dict | None: return self.getVerification(verification_id)
    def checkVerificationStatus(self, verification_id: str) -> str | None:
        item = self.getVerification(verification_id)
        return item["verification_status"] if item else None
    def validateReceipt(self, verification_id: str) -> bool:
        item = self.getVerification(verification_id)
        return bool(item and sha256(canonicalize({k: v for k, v in item.items() if k != "canonical_verification_hash"})) == item["canonical_verification_hash"])


class XRPLAuditPublisher:
    """Moten-owned publication governance facade; no source system receives signer access."""
    def __init__(self, service: AuditService): self.service = service
    def publish(self, request_id: str) -> dict: return self.service.publish(request_id)

