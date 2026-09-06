"""Initial inventory so the zone and lifecycle model is visible immediately.

Seeded state (per the product brief):
- three Midwest live examples with different production modes, one on backup,
- a cleared (green) Midwest event ready to go live,
- a Midwest replay,
- West and East inventory to make the zone model visible.
"""

from __future__ import annotations

import time

from .db import Database, dumps

HOUR = 3600
DAY = 24 * HOUR


def _user(uid, name, role, zones, packages, destinations,
          account_state="active", subscription="active"):
    return (uid, name, role, account_state, subscription,
            dumps(zones), dumps(packages), dumps(destinations))


def _has_rows(db: Database, table: str) -> bool:
    row = db.query_one(f"SELECT COUNT(*) AS c FROM {table}")
    return bool(row and row["c"])


def seed_if_empty(db: Database) -> bool:
    """Populate demo data if the database has no events yet. Returns True if seeded."""
    # Always upsert demo identities so existing pilot databases gain newly
    # introduced roles without requiring destructive data deletion.
    db.executemany(
        "INSERT OR REPLACE INTO users(user_id,display_name,role,account_state,subscription,"
        "zones,packages,destinations) VALUES (?,?,?,?,?,?,?,?)",
        [
            # Member site: a subscriber who can only watch what they are entitled to.
            _user("demo-viewer", "Demo Member (viewer)", "viewer",
                  ["midwest"], ["standard"], ["web"]),
            # Back worker side: production staff who run events but cannot see the owner portal.
            _user("demo-worker", "Demo Worker (operator)", "operator",
                  ["*"], ["*"], ["*"]),
            # Owner side: full control plus the print-everything back portal.
            _user("demo-owner", "Demo Owner", "owner",
                  ["*"], ["*"], ["*"]),
        ],
    )
    # V1 used demo-admin. The explicit three-tier model replaces it with the
    # owner account; historical audit rows keep their original actor string.
    db.execute("DELETE FROM users WHERE user_id=?", ("demo-admin",))

    if _has_rows(db, "events"):
        return False

    now = time.time()

    events: list[tuple] = []
    rights: list[tuple] = []

    def add(event_id, title, zone, status, mode, offset_hours, category="general",
            primary_fresh=False, backup_fresh=False, active_source="primary",
            replay_available=0, scoreboard=None, revoked=False, version=1):
        start = now + offset_hours * HOUR
        p_seen = now if primary_fresh else None
        b_seen = now if backup_fresh else None
        events.append((
            event_id, title, zone, category, status, start, mode, active_source,
            p_seen, b_seen, dumps(scoreboard or {}), replay_available, now,
        ))
        rights.append((
            event_id, version, zone, "web", "standard",
            start - HOUR, start + 3 * HOUR,           # live window
            start - HOUR, start + 30 * DAY,           # replay window
            "State Athletic Association", f"contract://{event_id}",
            0 if revoked else 1, 1 if revoked else 0,
            "seed revocation" if revoked else None, 365, now,
        ))

    # Three Midwest live examples, distinct production modes, one on backup.
    add("evt_mw_basketball", "Lincoln Freshman Basketball", "midwest", "live",
        "single_camera", -0.5, "basketball", primary_fresh=True,
        scoreboard={"home": 34, "away": 29, "period": "Q3", "clock": "05:12"})
    add("evt_mw_volleyball", "Lakeside Volleyball", "midwest", "green",
        "multi_camera", 0.25, "volleyball", primary_fresh=True,
        scoreboard={"home": 1, "away": 1, "period": "Set 3", "clock": "18-16"})
    add("evt_mw_soccer", "Prairie Soccer Semifinal", "midwest", "live",
        "backup_active", -0.25, "soccer", backup_fresh=True, active_source="backup",
        scoreboard={"home": 2, "away": 1, "period": "2nd", "clock": "62:40"})

    # A cleared (green) event and a replay in the Midwest zone.
    add("evt_mw_hockey", "Northside Hockey", "midwest", "green",
        "single_camera", 1.0, "hockey", primary_fresh=True)
    add("evt_mw_wrestling", "Central Wrestling (Archive)", "midwest", "archive",
        "single_camera", -3.0, "wrestling", replay_available=1,
        scoreboard={"home": 42, "away": 30, "period": "Final", "clock": "--"})

    # West and East inventory to make the zone model visible.
    add("evt_w_football", "Coastal Football", "west", "scheduled",
        "multi_camera", 5.0, "football")
    add("evt_w_baseball", "Harbor Baseball (Replay)", "west", "replay",
        "single_camera", -6.0, "baseball", replay_available=1,
        scoreboard={"home": 5, "away": 3, "period": "Final", "clock": "--"})
    add("evt_e_lacrosse", "Metro Lacrosse", "east", "yellow",
        "single_camera", 3.0, "lacrosse")

    db.executemany(
        "INSERT INTO events(event_id,title,zone,category,status,scheduled_start,production_mode,"
        "active_source,primary_last_seen,backup_last_seen,scoreboard,replay_available,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        events,
    )
    db.executemany(
        "INSERT INTO rights(event_id,version,territory,destination,package,live_start,live_end,"
        "replay_start,replay_end,authority,source_reference,active,revoked,revocation_reason,"
        "archive_retention_days,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rights,
    )
    db.execute("INSERT INTO audit(ts,actor,action,event_id,detail) VALUES (?,?,?,?,?)",
               (now, "system", "seed.loaded", None, dumps({"events": len(events)})))
    return True
