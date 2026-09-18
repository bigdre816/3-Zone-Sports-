"""Versioned member points ledger.

Awards are append-only. Changing a rule later never rewrites history.
``legal_effect`` of related audit rows is provenance only — not a filing date.
"""

from __future__ import annotations

import uuid

RULE_VERSION = "TZ-POINTS-2026.1"
DEFAULT_AMOUNTS = {
    "post.published": 10,
    "clip.published": 15,
    "game.completed": 25,
    "reaction.received": 2,
}


def _id() -> str:
    return "pts_" + uuid.uuid4().hex[:16]


def _now() -> float:
    import time
    return time.time()


class PointsLedger:
    def __init__(self, cp):
        self.cp = cp
        self.db = cp.db

    def current_version(self) -> str:
        row = self.db.query_one(
            "SELECT rule_version FROM point_rules WHERE active=1 ORDER BY rule_version DESC"
        )
        return row["rule_version"] if row else RULE_VERSION

    def amount_for(self, event_type: str) -> int:
        version = self.current_version()
        row = self.db.query_one(
            "SELECT amount FROM point_rules WHERE rule_version=? AND event_type=? AND active=1",
            (version, event_type),
        )
        if row:
            return int(row["amount"])
        return int(DEFAULT_AMOUNTS.get(event_type, 0))

    def total_for_profile(self, profile_id: str) -> dict:
        row = self.db.query_one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM point_ledger "
            "WHERE profile_id=? AND status='counted'",
            (profile_id,),
        )
        total = int(row["total"] if row else 0)
        return {"total": total, "rule_version": self.current_version()}

    def entries_for_profile(self, profile_id: str, limit: int = 100) -> list[dict]:
        """Read-only ledger lines for the owning member.

        Reads the same append-only rows the awards write. No second authority,
        no recomputation: what the member sees is what the ledger recorded.
        """
        limit = max(1, min(int(limit or 100), 200))
        rows = self.db.query(
            "SELECT ledger_id, event_type, amount, rule_version, subject_type, subject_id, "
            "status, recorded_at FROM point_ledger WHERE profile_id=? "
            "ORDER BY recorded_at DESC LIMIT ?",
            (profile_id, limit),
        )
        return [dict(row) for row in rows]

    def actor_is_suspicious(self, user: dict, actor_profile_id: str) -> bool:
        if not user or user.get("account_state") != "active":
            return True
        if user.get("subscription") != "active":
            return True
        open_case = self.db.query_one(
            "SELECT 1 FROM moderation_cases WHERE subject_type='profile' AND subject_id=? "
            "AND policy_decision IS NULL",
            (actor_profile_id,),
        )
        return bool(open_case)

    def _already_awarded(self, event_type: str, subject_type: str, subject_id: str,
                         actor_profile_id: str | None) -> bool:
        if event_type == "reaction.received":
            row = self.db.query_one(
                "SELECT 1 FROM point_ledger WHERE event_type=? AND subject_type=? AND subject_id=? "
                "AND actor_profile_id=? AND status IN ('counted','held')",
                (event_type, subject_type, subject_id, actor_profile_id),
            )
        else:
            row = self.db.query_one(
                "SELECT 1 FROM point_ledger WHERE event_type=? AND subject_type=? AND subject_id=? "
                "AND status IN ('counted','held')",
                (event_type, subject_type, subject_id),
            )
        return bool(row)

    def award(self, *, beneficiary_profile_id: str, event_type: str, subject_type: str,
              subject_id: str, actor_profile_id: str | None = None, actor_user: dict | None = None,
              hold: bool = False) -> dict | None:
        amount = self.amount_for(event_type)
        if amount <= 0 or not beneficiary_profile_id:
            return None
        actor_profile_id = actor_profile_id or beneficiary_profile_id
        if self._already_awarded(event_type, subject_type, subject_id, actor_profile_id):
            return None
        status = "held" if hold else "counted"
        if actor_user is not None and self.actor_is_suspicious(actor_user, actor_profile_id):
            status = "held"
        version = self.current_version()
        ledger_id = _id()
        self.db.execute(
            "INSERT INTO point_ledger(ledger_id, profile_id, event_type, amount, rule_version, "
            "actor_profile_id, subject_type, subject_id, status, recorded_at, reverses_ledger_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ledger_id, beneficiary_profile_id, event_type, amount, version,
             actor_profile_id, subject_type, subject_id, status, _now(), None),
        )
        self.cp.audit_log(
            actor_user["user_id"] if actor_user else "system",
            "points.awarded",
            subject_id,
            {
                "ledger_id": ledger_id,
                "event_type": event_type,
                "amount": amount,
                "rule_version": version,
                "status": status,
                "legal_effect": "provenance_only",
            },
        )
        return {"ledger_id": ledger_id, "amount": amount, "status": status, "rule_version": version}

    def reverse_reaction(self, actor_profile_id: str, subject_type: str, subject_id: str,
                         actor_user: dict | None = None) -> dict | None:
        prior = self.db.query_one(
            "SELECT * FROM point_ledger WHERE event_type='reaction.received' AND subject_type=? "
            "AND subject_id=? AND actor_profile_id=? AND status IN ('counted','held') "
            "ORDER BY recorded_at DESC",
            (subject_type, subject_id, actor_profile_id),
        )
        if not prior:
            return None
        amount = -int(prior["amount"])
        ledger_id = _id()
        self.db.execute(
            "INSERT INTO point_ledger(ledger_id, profile_id, event_type, amount, rule_version, "
            "actor_profile_id, subject_type, subject_id, status, recorded_at, reverses_ledger_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ledger_id, prior["profile_id"], "reaction.received", amount, prior["rule_version"],
             actor_profile_id, subject_type, subject_id, "reversed", _now(), prior["ledger_id"]),
        )
        self.db.execute(
            "UPDATE point_ledger SET status='reversed' WHERE ledger_id=?",
            (prior["ledger_id"],),
        )
        self.cp.audit_log(
            actor_user["user_id"] if actor_user else "system",
            "points.reversed",
            subject_id,
            {
                "ledger_id": ledger_id,
                "reverses": prior["ledger_id"],
                "amount": amount,
                "rule_version": prior["rule_version"],
                "legal_effect": "provenance_only",
            },
        )
        return {"ledger_id": ledger_id, "amount": amount, "status": "reversed"}
