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
from .passwords import hash_password

HOUR = 3600
DAY = 24 * HOUR


def _user(uid, name, role, zones, packages, destinations,
          account_state="active", subscription="active", password_hash=""):
    return (uid, name, role, account_state, subscription,
            dumps(zones), dumps(packages), dumps(destinations), password_hash)


def _has_rows(db: Database, table: str) -> bool:
    row = db.query_one(f"SELECT COUNT(*) AS c FROM {table}")
    return bool(row and row["c"])


def seed_if_empty(db: Database, seed_passwords: dict | None = None) -> bool:
    """Populate demo data if the database has no events yet. Returns True if seeded."""
    from .config import DEMO_SEED_PASSWORDS
    passwords = seed_passwords or DEMO_SEED_PASSWORDS
    # Always upsert demo identities so existing pilot databases gain newly
    # introduced roles without requiring destructive data deletion.
    db.executemany(
        "INSERT OR REPLACE INTO users(user_id,display_name,role,account_state,subscription,"
        "zones,packages,destinations,password_hash) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            # Member site: a subscriber who can only watch what they are entitled to.
            _user("demo-viewer", "Demo Member (viewer)", "viewer",
                  ["midwest"], ["standard"], ["web"],
                  password_hash=hash_password(passwords.get("demo-viewer", DEMO_SEED_PASSWORDS["demo-viewer"]))),
            _user("demo-maya", "Maya", "viewer",
                  ["midwest"], ["standard"], ["web"],
                  password_hash=hash_password(passwords.get("demo-viewer", DEMO_SEED_PASSWORDS["demo-viewer"]))),
            _user("demo-chris", "Chris", "viewer",
                  ["midwest"], ["standard"], ["web"],
                  password_hash=hash_password(passwords.get("demo-viewer", DEMO_SEED_PASSWORDS["demo-viewer"]))),
            _user("demo-taylor", "Taylor", "viewer",
                  ["midwest"], ["standard"], ["web"],
                  password_hash=hash_password(passwords.get("demo-viewer", DEMO_SEED_PASSWORDS["demo-viewer"]))),
            # Back worker side: production staff who run events but cannot see the owner portal.
            _user("demo-worker", "Demo Worker (operator)", "operator",
                  ["*"], ["*"], ["*"],
                  password_hash=hash_password(passwords.get("demo-worker", DEMO_SEED_PASSWORDS["demo-worker"]))),
            # Owner side: full control plus the print-everything back portal.
            _user("demo-owner", "Demo Owner", "owner",
                  ["*"], ["*"], ["*"],
                  password_hash=hash_password(passwords.get("demo-owner", DEMO_SEED_PASSWORDS["demo-owner"]))),
        ],
    )
    # V1 used demo-admin. The explicit three-tier model replaces it with the
    # owner account; historical audit rows keep their original actor string.
    db.execute("DELETE FROM users WHERE user_id=?", ("demo-admin",))

    now = time.time()
    db.executemany(
        "INSERT OR IGNORE INTO profiles(profile_id,user_id,handle,display_name,avatar,bio,market,"
        "sports,profile_type,visibility,verification_state,verification_badge,team_id,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("prf_demo_viewer", "demo-viewer", "demo_viewer", "Demo Member (viewer)", "",
             "Midwest fan", "midwest", dumps(["basketball"]), "fan", "public", "none", "", None, now, now),
            ("prf_demo_maya", "demo-maya", "maya_kc", "Maya", "",
             "Kansas City hoops", "midwest", dumps(["basketball"]), "fan", "public", "none", "", None, now, now),
            ("prf_demo_chris", "demo-chris", "chris_kc", "Chris", "",
             "Ridgeview football", "midwest", dumps(["football"]), "fan", "public", "none", "", None, now, now),
            ("prf_demo_taylor", "demo-taylor", "taylor_kc", "Taylor", "",
             "KC soccer", "midwest", dumps(["soccer"]), "fan", "public", "none", "", None, now, now),
            ("prf_demo_worker", "demo-worker", "demo_worker", "Demo Worker (operator)", "",
             "Operations", "midwest", dumps([]), "videographer", "public", "none", "", None, now, now),
            ("prf_demo_owner", "demo-owner", "demo_owner", "Demo Owner", "",
             "Owner", "midwest", dumps([]), "sports_organization", "public", "none", "", None, now, now),
        ],
    )

    if _has_rows(db, "events"):
        _backfill_property_ids(db)
        _backfill_kc_huddle(db)
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
    _backfill_property_ids(db)
    _backfill_kc_huddle(db)
    return True


def _backfill_property_ids(db: Database) -> None:
    """Attach seeded Midwest events to Lincoln High so property audit has a school."""
    db.execute(
        "UPDATE events SET property_id='school_lincoln' "
        "WHERE property_id IS NULL AND zone='midwest'"
    )
    db.execute(
        "UPDATE events SET property_id='school_lincoln' "
        "WHERE event_id IN ('evt_mw_basketball','evt_mw_hockey','evt_mw_wrestling')"
    )
    db.execute(
        "UPDATE events SET property_id='school_lakeside' WHERE event_id='evt_mw_volleyball'"
    )


def _backfill_kc_huddle(db: Database) -> None:
    """Kansas City metro high-school inventory and watchable YouTube clips.

    INSERT OR IGNORE so existing Render SQLite disks pick this up on restart
    without wiping member accounts. Video ids are public, embeddable YouTube
    sports stock (Creative Commons / royalty-free where available) so the
    Huddle can actually play in-feed. Captions describe Kansas City sports;
    licensed game film is not bundled in this repo.
    """
    now = time.time()
    db.executemany("INSERT OR IGNORE INTO schools VALUES (?,?,?)", [
        ("school_northview", "Northview High (Kansas City)", "midwest"),
        ("school_ridgewood", "Ridgewood High (Kansas City)", "midwest"),
        ("school_ridgeview", "Ridgeview High (Kansas City)", "midwest"),
        ("school_westlake", "Westlake High (Kansas City)", "midwest"),
    ])
    db.executemany("INSERT OR IGNORE INTO teams VALUES (?,?,?,?,?)", [
        ("team_northview_bball", "school_northview", "Northview Wolves Basketball", "basketball", "varsity"),
        ("team_ridgewood_bball", "school_ridgewood", "Ridgewood Tigers Basketball", "basketball", "varsity"),
        ("team_ridgeview_fb", "school_ridgeview", "Ridgeview Panthers Football", "football", "varsity"),
        ("team_westlake_fb", "school_westlake", "Westlake Bulldogs Football", "football", "varsity"),
        ("team_kc_soccer", "school_northview", "Kansas City Youth Soccer", "soccer", "varsity"),
        ("team_northview_vb", "school_northview", "Northview Volleyball", "volleyball", "varsity"),
        ("team_kc_baseball", "school_ridgewood", "KC Metro Baseball", "baseball", "varsity"),
    ])

    def add_event(event_id, title, status, offset_hours, category, scoreboard, school_id):
        start = now + offset_hours * HOUR
        db.execute(
            "INSERT OR IGNORE INTO events(event_id,title,zone,category,status,scheduled_start,"
            "production_mode,active_source,primary_last_seen,backup_last_seen,scoreboard,"
            "replay_available,created_at,property_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, title, "midwest", category, status, start, "single_camera", "primary",
             now if status == "live" else None, None, dumps(scoreboard or {}),
             1 if status == "archive" else 0, now, school_id),
        )
        db.execute(
            "INSERT OR IGNORE INTO rights(event_id,version,territory,destination,package,"
            "live_start,live_end,replay_start,replay_end,authority,source_reference,active,"
            "revoked,revocation_reason,archive_retention_days,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, 1, "midwest", "web", "standard", start - HOUR, start + 3 * HOUR,
             start - HOUR, start + 30 * DAY, "Kansas City Metro Athletics",
             f"contract://{event_id}", 1, 0, None, 365, now),
        )

    add_event(
        "evt_kc_bball", "Northview Wolves vs Ridgewood Tigers", "live", -0.4, "basketball",
        {"home": 72, "away": 68, "period": "Final", "clock": "0:00"}, "school_northview",
    )
    add_event(
        "evt_kc_live_bball", "Ridgeview Panthers vs Westlake Bulldogs", "live", -0.2, "basketball",
        {"home": 58, "away": 52, "period": "Q4", "clock": "4:27"}, "school_ridgeview",
    )
    add_event(
        "evt_kc_football", "Ridgeview High vs Westlake", "green", 0.5, "football",
        {"home": 21, "away": 14, "period": "Q3", "clock": "6:12"}, "school_ridgeview",
    )
    add_event(
        "evt_kc_soccer", "Kansas City Youth Soccer", "scheduled", 8.0, "soccer",
        None, "school_northview",
    )
    add_event(
        "evt_kc_vball", "Northview Volleyball", "green", 1.5, "volleyball",
        {"home": 2, "away": 1, "period": "Set 3", "clock": "24-22"}, "school_northview",
    )
    add_event(
        "evt_kc_baseball", "KC Metro Baseball", "archive", -20.0, "baseball",
        {"home": 5, "away": 3, "period": "Final", "clock": "--"}, "school_ridgewood",
    )

    clips = [
        ("pst_kc_poster", "med_yt_kc_poster", "wtpobZDZv3A", "basketball",
         "Andre's poster puts the crowd on its feet! #Basketball #Highlights #ThreeZone Northview vs Ridgewood, Kansas City."),
        ("pst_kc_steal", "med_yt_kc_steal", "Ff_CRZQ01mw", "football",
         "Game-changing steal — Ridgeview Panthers, Kansas City. Football night."),
        ("pst_kc_clutch", "med_yt_kc_clutch", "M7lc1UVf-VE", "basketball",
         "Clutch drive seals the win. Northview Wolves basketball."),
        ("pst_kc_soccer", "med_yt_kc_soccer", "DD2wMzJ215g", "soccer",
         "A team that plays for each other. Kansas City Youth Soccer."),
        ("pst_kc_vball", "med_yt_kc_vball", "8vlsXetUOus", "volleyball",
         "Northview volleyball — set, swing, Kansas City."),
        ("pst_kc_baseball", "med_yt_kc_baseball", "pRpeEdMmmQ0", "soccer",
         "Walk-up energy on a Kansas City soccer night. Watch it in the Huddle."),
    ]
    author = "prf_demo_viewer"
    for i, (post_id, asset_id, video_id, sport, caption) in enumerate(clips):
        stamp = now - i * 3600
        db.execute(
            "INSERT OR IGNORE INTO media_assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, author, "youtube", video_id, "youtube", None, None, "ready",
             "video/youtube", stamp, stamp),
        )
        db.execute(
            "UPDATE media_assets SET provider_uid=?, kind='youtube', provider='youtube' WHERE media_asset_id=?",
            (video_id, asset_id),
        )
        db.execute(
            "INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (post_id, author, asset_id, None, caption, sport, "public", "published", 1,
             None, stamp, stamp, stamp),
        )
        db.execute(
            "UPDATE posts SET caption=?, sport=? WHERE post_id=?",
            (caption, sport, post_id),
        )
    db.executemany("INSERT OR IGNORE INTO team_follows VALUES (?,?,?)", [
        (author, "team_northview_bball", now),
        (author, "team_ridgeview_fb", now),
        (author, "team_ridgewood_bball", now),
        (author, "team_kc_soccer", now),
    ])
    db.executemany("INSERT OR IGNORE INTO comments VALUES (?,?,?,?,?,?,?,?)", [
        ("cmt_kc_maya", "post", "pst_kc_poster", "prf_demo_maya", "That dunk was crazyyy", now - 300, None, None),
        ("cmt_kc_chris", "post", "pst_kc_poster", "prf_demo_chris", "Different breed. Future star.", now - 240, None, None),
        ("cmt_kc_taylor", "post", "pst_kc_poster", "prf_demo_taylor", "Northview is built different this year.", now - 180, None, None),
    ])
    db.execute("UPDATE comments SET author_profile_id='prf_demo_maya' WHERE comment_id='cmt_kc_maya'")
    db.execute("UPDATE comments SET author_profile_id='prf_demo_chris' WHERE comment_id='cmt_kc_chris'")
    db.execute("UPDATE comments SET author_profile_id='prf_demo_taylor' WHERE comment_id='cmt_kc_taylor'")

    def _friend_pair(a, b):
        return (a, b) if a < b else (b, a)

    for other in ("prf_demo_maya", "prf_demo_chris", "prf_demo_taylor"):
        left, right = _friend_pair(author, other)
        fid = "frn_" + left[-8:] + right[-4:]
        db.execute(
            "INSERT OR IGNORE INTO friendships VALUES (?,?,?,?,?,?,?)",
            (fid, left, right, "accepted", other, now, now),
        )
        db.execute(
            "INSERT OR IGNORE INTO member_settings VALUES (?,?,?,?)",
            (other, {"prf_demo_maya": "demo-maya", "prf_demo_chris": "demo-chris",
                     "prf_demo_taylor": "demo-taylor"}[other], 1, now),
        )
        db.execute(
            "UPDATE member_settings SET show_watching_to_friends=1 WHERE profile_id=?",
            (other,),
        )
    db.execute(
        "INSERT OR IGNORE INTO view_sessions(session_id,event_id,user_id,pseudonym,lease_id,rights_id,"
        "rights_version,started_at,ended_at,last_seq,last_heartbeat_at,qualified_seconds,"
        "state,close_reason,digest,canonical_json,property_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("VS-KC-MAYA", "evt_kc_live_bball", "demo-maya", "maya", "lease_kc_maya",
         None, 1, now, None, 0, now, 0, "open", None, None, None, "school_ridgeview"),
    )
    db.execute(
        "INSERT OR IGNORE INTO view_sessions(session_id,event_id,user_id,pseudonym,lease_id,rights_id,"
        "rights_version,started_at,ended_at,last_seq,last_heartbeat_at,qualified_seconds,"
        "state,close_reason,digest,canonical_json,property_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("VS-KC-CHRIS", "evt_kc_football", "demo-chris", "chris", "lease_kc_chris",
         None, 1, now, None, 0, now, 0, "open", None, None, None, "school_ridgeview"),
    )
