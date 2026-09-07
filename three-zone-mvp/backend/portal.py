"""Server-authoritative Three-Zone Sports Access member-portal domains.

The adapter simulations are intentionally explicit: DEMO can exercise the
integration loop without external infrastructure; non-DEMO environments fail
closed when a required upstream authority is unavailable.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import uuid

from .control_plane import ForbiddenError, ValidationError
from .db import dumps, loads


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(dumps(value).encode()).hexdigest()


class PortalService:
    def __init__(self, cp):
        self.cp = cp
        self.db = cp.db

    def audit(self, event_type, subject_id=None, actor_type="system", actor_id="system",
              payload=None, correlation_id=None, verification_ref=None, rights_version=None):
        payload = payload or {}
        last = self.db.query_one("SELECT payload_hash FROM audit_events ORDER BY recorded_at DESC LIMIT 1")
        event_id = _id("AUD")
        stamp = time.time()
        payload_hash = _hash(payload)
        self.db.execute(
            "INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, event_type, "three-zone", "three-zone-api", subject_id, actor_type, actor_id,
             stamp, stamp, "1.0", dumps(payload), payload_hash,
             last["payload_hash"] if last else None, correlation_id, verification_ref,
             str(rights_version) if rights_version is not None else None, "operational_record"),
        )
        # The legacy stream remains available to existing control-plane users.
        self.cp.audit_log(actor_id or "system", event_type, subject_id, payload)
        return event_id

    # Treasure Verification Gateway -------------------------------------------------
    def verify_treasure(self, member_id: str, verification_type="member_access"):
        if self.cp.config.env not in ("demo", "development", "local"):
            raise ForbiddenError("verification service unavailable", "verification_unavailable")
        now = time.time()
        verification_id, receipt_id = _id("VER"), _id("TRR")
        evidence = _hash({"member_id": member_id, "type": verification_type, "at": now})
        self.db.execute(
            "INSERT INTO member_verifications VALUES (?,?,?,?,?,?,?,?,?,?)",
            (verification_id, member_id, "VERIFIED", verification_type, now, now + 3600,
             evidence, "treasure-network", receipt_id, 1),
        )
        self.audit("treasure.verification.completed", verification_id, "service", "treasure-verification-adapter",
                   {"simulated": True, "receipt_id": receipt_id}, verification_ref=verification_id)
        return {"verification_id": verification_id, "subject_ref": member_id, "status": "VERIFIED",
                "verification_type": verification_type, "verified_at": now, "expires_at": now + 3600,
                "evidence_hash": evidence, "verifier": "treasure-network", "receipt_id": receipt_id,
                "simulated": True}

    def verification_valid(self, member_id: str, verification_id: str | None):
        if not verification_id:
            return False
        row = self.db.query_one("SELECT * FROM member_verifications WHERE verification_id=? AND member_id=?",
                                (verification_id, member_id))
        return bool(row and row["status"] == "VERIFIED" and row["expires_at"] > time.time())

    # Session + entitlement ---------------------------------------------------------
    def start_auth(self, identifier: str):
        member_id = identifier if identifier in ("demo-viewer", "andre") else "demo-viewer"
        self.audit("member.login.requested", member_id, "member", member_id)
        return {"member_id": member_id, "next": "verify", "demo": self.cp.config.env in ("demo", "development", "local")}

    def complete_auth(self, member_id: str):
        user = self.cp.get_user(member_id)
        if not user:
            raise ForbiddenError("member unavailable", "member_unavailable")
        verification = self.verify_treasure(member_id)
        if user["account_state"] != "active" or user["subscription"] != "active":
            self.audit("member.login.denied", member_id, "member", member_id,
                       {"reason": "entitlement_inactive"}, verification_ref=verification["verification_id"])
            raise ForbiddenError("Access is not currently available.", "entitlement_denied")
        session_id = _id("SES")
        now = time.time()
        self.db.execute("INSERT INTO member_sessions VALUES (?,?,?,?,?,?,?, ?,?)",
                        (session_id, member_id, verification["verification_id"], 1, "demo-browser",
                         "active", now, now + self.cp.config.session_ttl, None))
        self.audit("member.login.success", session_id, "member", member_id,
                   verification_ref=verification["verification_id"])
        return {"session_id": session_id, "expires_at": now + self.cp.config.session_ttl,
                "member": {"member_id": member_id, "display_name": user["display_name"]},
                "verification": verification}

    def session(self, session_id):
        row = self.db.query_one("SELECT * FROM member_sessions WHERE session_id=?", (session_id,))
        if not row or row["status"] != "active" or row["expires_at"] <= time.time():
            raise ForbiddenError("session expired", "invalid_session")
        if not self.verification_valid(row["member_id"], row["verification_id"]):
            raise ForbiddenError("verification required", "verification_required")
        user = self.cp.get_user(row["member_id"])
        if not user or user["account_state"] != "active" or user["subscription"] != "active":
            raise ForbiddenError("Access is not currently available.", "entitlement_denied")
        return row, user

    def logout(self, session_id):
        self.db.execute("UPDATE member_sessions SET status='revoked', revoked_at=? WHERE session_id=?",
                        (time.time(), session_id))

    # Catalog ----------------------------------------------------------------------
    def _ensure_catalog(self):
        if self.db.query_one("SELECT school_id FROM schools LIMIT 1"):
            return
        self.db.executemany("INSERT INTO schools VALUES (?,?,?)", [
            ("school_lincoln", "Lincoln High", "midwest"), ("school_lakeside", "Lakeside Prep", "midwest"),
            ("school_north", "Northridge", "midwest")])
        self.db.executemany("INSERT INTO teams VALUES (?,?,?,?,?)", [
            ("team_lincoln_bball", "school_lincoln", "Lincoln Freshman Basketball", "basketball", "freshman"),
            ("team_lakeside_bball", "school_lakeside", "Lakeside Prep Basketball", "basketball", "varsity"),
            ("team_north_soccer", "school_north", "Northridge Soccer", "soccer", "varsity")])
        sid = "sch-lincoln-2026"
        stamp = time.time()
        self.db.execute("INSERT INTO schedules VALUES (?,?,?,?,?,?)",
                        (sid, "school_lincoln", "team_lincoln_bball", "2026", 1, "active"))
        self.db.execute("INSERT INTO schedule_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (sid, 1, "fixture", "demo-fixtures", _hash({"schedule": sid}), "system",
                         stamp, stamp, None, "active"))
        self.db.executemany("INSERT INTO schedule_events VALUES (?,?,?,?,?,?,?,?)", [
            (sid, 1, "sce-lincoln-1", "Central Valley", stamp + 86400, "Riverside Stadium", "HOME", 1),
            (sid, 1, "sce-lincoln-2", "Maple Grove", stamp + 172800, "Lakeside Gym", "AWAY", 2)])
        self.db.execute("INSERT INTO archive_objects VALUES (?,?,?,?,?,?,?,?,?)",
                        ("arc-central-wrestling", "evt_mw_wrestling", "school_lincoln", "team_lincoln_bball",
                         "2026", "Full Game", "Central Wrestling — Full Game", "", "ARCHIVED"))

    def live(self, user):
        self._ensure_catalog()
        events = self.cp.list_events(user)
        result = [e for e in events if e["status"] in ("live", "green", "scheduled")]
        self.audit("event.discovered", "live-catalog", "member", user["user_id"], {"count": len(result)})
        return result

    def schedules(self, user, filters=None):
        self._ensure_catalog()
        filters = filters or {}
        sql = """SELECT se.*,s.season,t.name team,t.sport,t.level,sc.name school FROM schedules s
                 JOIN schedule_events se ON se.schedule_id=s.schedule_id AND se.version=s.current_version
                 JOIN teams t ON t.team_id=s.team_id JOIN schools sc ON sc.school_id=s.school_id WHERE 1=1"""
        params = []
        for field, column in (("school_id", "s.school_id"), ("team_id", "s.team_id"), ("season", "s.season"), ("sport", "t.sport"), ("level", "t.level")):
            if filters.get(field):
                sql += f" AND {column}=?"; params.append(filters[field])
        sql += " ORDER BY se.start_at"
        return [dict(r) for r in self.db.query(sql, tuple(params))]

    def archives(self, user, filters=None):
        self._ensure_catalog()
        rows = self.db.query("""SELECT a.*,sc.name school,t.name team,t.sport,t.level FROM archive_objects a
                              JOIN schools sc ON sc.school_id=a.school_id JOIN teams t ON t.team_id=a.team_id
                              WHERE a.status='ARCHIVED' ORDER BY a.season DESC,a.title""")
        return [dict(r) for r in rows]

    def search(self, user, query):
        q = "%" + (query or "").lower() + "%"
        results = []
        for r in self.db.query("SELECT school_id,name,'school' kind FROM schools WHERE lower(name) LIKE ?", (q,)):
            results.append(dict(r))
        for r in self.db.query("SELECT team_id,name,'team' kind FROM teams WHERE lower(name) LIKE ?", (q,)):
            results.append(dict(r))
        for e in self.cp.list_events(user):
            if query.lower() in e["title"].lower() or query.lower() in e["category"].lower():
                results.append({"id": e["event_id"], "name": e["title"], "kind": "game"})
        return results[:30]

    # Playback ---------------------------------------------------------------------
    def playback(self, session_id, event_id, use="live"):
        session, user = self.session(session_id)
        self.audit("playback.requested", event_id, "member", user["user_id"], verification_ref=session["verification_id"])
        event = self.cp.get_event_row(event_id)
        if use == "archive" and event["status"] != "archive":
            raise ForbiddenError("This game is not currently available with your access.", "archive_not_authorized")
        try:
            lease = self.cp.request_playback(event_id, user)
        except ForbiddenError:
            self.audit("lease.denied", event_id, "member", user["user_id"])
            raise ForbiddenError("This game is not currently available with your access.", "playback_denied")
        self.db.execute("INSERT INTO lease_records VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (lease["lease_id"], event_id, user["user_id"], session_id, lease["rights_version"],
                         lease["mode"], "active", time.time(), time.time() + lease["lease_ttl"], None))
        self.audit("lease.issued", lease["lease_id"], "system", "rights-service",
                   {"event_id": event_id, "simulated_media": True}, verification_ref=session["verification_id"],
                   rights_version=lease["rights_version"])
        return lease

    # schedules --------------------------------------------------------------------
    def upload_schedule(self, operator, filename, content):
        self.cp.require_operator(operator)
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        errors, parsed = [], []
        required = ("school", "team", "sport", "level", "opponent", "date", "start time", "location", "home/away", "season")
        for number, row in enumerate(rows, 2):
            missing = [f for f in required if not row.get(f)]
            if missing:
                errors.append({"row": number, "error": "missing " + ", ".join(missing)}); continue
            try: start = time.mktime(time.strptime(row["date"] + " " + row["start time"], "%Y-%m-%d %H:%M"))
            except ValueError: errors.append({"row": number, "error": "invalid date"}); continue
            parsed.append((number, row, start))
        if errors:
            return {"accepted": False, "errors": errors}
        first = parsed[0][1]; school = self.db.query_one("SELECT * FROM schools WHERE name=?", (first["school"],))
        team = self.db.query_one("SELECT * FROM teams WHERE name=?", (first["team"],))
        if not school or not team:
            return {"accepted": False, "errors": [{"row": 2, "error": "unknown school or team"}]}
        schedule = self.db.query_one("SELECT * FROM schedules WHERE team_id=? AND season=?", (team["team_id"], first["season"]))
        sid = schedule["schedule_id"] if schedule else _id("SCH"); version = (schedule["current_version"] + 1) if schedule else 1
        seen = set()
        for n, row, start in parsed:
            key = (row["opponent"], start)
            if key in seen: errors.append({"row": n, "error": "duplicate event"})
            seen.add(key)
        if errors: return {"accepted": False, "errors": errors}
        if schedule: self.db.execute("UPDATE schedules SET current_version=? WHERE schedule_id=?", (version, sid))
        else: self.db.execute("INSERT INTO schedules VALUES (?,?,?,?,?,?)", (sid, school["school_id"], team["team_id"], first["season"], version, "active"))
        stamp = time.time()
        self.db.execute("INSERT INTO schedule_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (sid, version, "csv", filename, digest, operator["user_id"], stamp, stamp, version-1 or None, "active"))
        self.db.executemany("INSERT INTO schedule_events VALUES (?,?,?,?,?,?,?,?)", [
            (sid, version, _id("SCE"), r["opponent"], start, r["location"], r["home/away"], n) for n, r, start in parsed])
        self.audit("schedule.version.created", sid, "operator", operator["user_id"],
                   {"version": version, "file_hash": digest, "rows": len(parsed)})
        return {"accepted": True, "schedule_id": sid, "version": version, "rows": len(parsed)}

    def publish_pending(self):
        """Moten adapter + XRPL simulation; only hash manifests are publishable."""
        pending = self.db.query("""SELECT a.* FROM audit_events a LEFT JOIN xrpl_publications x ON x.audit_event_id=a.event_id
                                   WHERE x.audit_event_id IS NULL ORDER BY a.recorded_at""")
        published = []
        for row in pending:
            pid = _id("XRP"); manifest = _hash({"audit_event_id": row["event_id"], "payload_hash": row["payload_hash"]})
            now = time.time()
            tx = "DEMO-" + hashlib.sha256(manifest.encode()).hexdigest()[:24]
            self.db.execute("INSERT INTO xrpl_publications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (pid, row["event_id"], row["payload_hash"], manifest, "demo-audit-account", tx,
                             "simulated-ledger", now, now, "VALIDATED", None, 0, 1))
            published.append(pid)
        return published

    def audit_detail(self, operator, event_id):
        self.cp.require_operator(operator)
        row = self.db.query_one("SELECT * FROM audit_events WHERE event_id=?", (event_id,))
        if not row: raise ValidationError("audit event not found", "audit_not_found")
        pub = self.db.query_one("SELECT * FROM xrpl_publications WHERE audit_event_id=?", (event_id,))
        return {"event": dict(row), "xrpl": dict(pub) if pub else None}
