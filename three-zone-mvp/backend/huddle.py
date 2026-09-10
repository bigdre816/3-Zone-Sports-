"""Huddle runtime: friends, moments, watch parties, ranking, Moten clip evidence.

Operating-company social data stays in Three-Zone. Moten only receives
evidence-grade handoffs after the local transaction commits.
"""

from __future__ import annotations

import time
import uuid

from .control_plane import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .db import dumps, loads


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


def _safe_text(value: str, limit: int = 2000) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise ValidationError(f"text exceeds {limit} characters", "text_too_long")
    return text


FRIEND_STATUSES = {"pending", "accepted", "declined", "blocked"}
PARTY_VISIBILITY = {"friends", "invite"}
MOMENT_STATUSES = {"candidate", "publishable", "held"}


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


class HuddleExtensions:
    """Mixin for :class:`NetworkService`."""

    def ensure_settings(self, user) -> dict:
        profile = self.ensure_profile(user)
        row = self.db.query_one(
            "SELECT * FROM member_settings WHERE profile_id=?", (profile["profile_id"],)
        )
        if row:
            return dict(row)
        stamp = _now()
        self.db.execute(
            "INSERT INTO member_settings VALUES (?,?,?,?)",
            (profile["profile_id"], user["user_id"], 0, stamp),
        )
        return dict(self.db.query_one(
            "SELECT * FROM member_settings WHERE profile_id=?", (profile["profile_id"],)
        ))

    def update_settings(self, user, data: dict) -> dict:
        settings = self.ensure_settings(user)
        data = data or {}
        show = settings["show_watching_to_friends"]
        if "show_watching_to_friends" in data:
            show = 1 if data.get("show_watching_to_friends") else 0
        self.db.execute(
            "UPDATE member_settings SET show_watching_to_friends=?, updated_at=? WHERE profile_id=?",
            (show, _now(), settings["profile_id"]),
        )
        return {
            "show_watching_to_friends": bool(show),
        }

    def get_settings(self, user) -> dict:
        settings = self.ensure_settings(user)
        return {"show_watching_to_friends": bool(settings["show_watching_to_friends"])}

    # -- follows (teams / schools) ---------------------------------------
    def follow_team(self, user, team_id: str) -> dict:
        profile = self.ensure_profile(user)
        team = self.db.query_one("SELECT * FROM teams WHERE team_id=?", (team_id,))
        if not team:
            raise NotFoundError("team not found", "team_not_found")
        self.db.execute(
            "INSERT OR IGNORE INTO team_follows VALUES (?,?,?)",
            (profile["profile_id"], team_id, _now()),
        )
        return {"ok": True, "following": True, "team_id": team_id}

    def unfollow_team(self, user, team_id: str) -> dict:
        profile = self.ensure_profile(user)
        self.db.execute(
            "DELETE FROM team_follows WHERE profile_id=? AND team_id=?",
            (profile["profile_id"], team_id),
        )
        return {"ok": True, "following": False, "team_id": team_id}

    def follow_school(self, user, school_id: str) -> dict:
        profile = self.ensure_profile(user)
        school = self.db.query_one("SELECT * FROM schools WHERE school_id=?", (school_id,))
        if not school:
            raise NotFoundError("school not found", "school_not_found")
        self.db.execute(
            "INSERT OR IGNORE INTO school_follows VALUES (?,?,?)",
            (profile["profile_id"], school_id, _now()),
        )
        return {"ok": True, "following": True, "school_id": school_id}

    def unfollow_school(self, user, school_id: str) -> dict:
        profile = self.ensure_profile(user)
        self.db.execute(
            "DELETE FROM school_follows WHERE profile_id=? AND school_id=?",
            (profile["profile_id"], school_id),
        )
        return {"ok": True, "following": False, "school_id": school_id}

    def _followed_team_ids(self, profile_id: str) -> set[str]:
        return {
            r["team_id"]
            for r in self.db.query("SELECT team_id FROM team_follows WHERE profile_id=?", (profile_id,))
        }

    def _is_blocked(self, a: str, b: str) -> bool:
        return bool(self.db.query_one(
            "SELECT 1 FROM member_blocks WHERE "
            "(blocker_profile_id=? AND blocked_profile_id=?) OR "
            "(blocker_profile_id=? AND blocked_profile_id=?)",
            (a, b, b, a),
        ))

    def block_member(self, user, handle: str) -> dict:
        actor = self.ensure_profile(user)
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        if actor["profile_id"] == target["profile_id"]:
            raise ValidationError("cannot block yourself", "self_block")
        self.db.execute(
            "INSERT OR IGNORE INTO member_blocks VALUES (?,?,?)",
            (actor["profile_id"], target["profile_id"], _now()),
        )
        self.db.execute(
            "DELETE FROM follows WHERE "
            "(follower_profile_id=? AND followed_profile_id=?) OR "
            "(follower_profile_id=? AND followed_profile_id=?)",
            (actor["profile_id"], target["profile_id"], target["profile_id"], actor["profile_id"]),
        )
        a, b = _pair(actor["profile_id"], target["profile_id"])
        self.db.execute(
            "UPDATE friendships SET status='blocked' WHERE member_a_id=? AND member_b_id=?",
            (a, b),
        )
        return {"ok": True, "blocked": True}

    def unblock_member(self, user, handle: str) -> dict:
        actor = self.ensure_profile(user)
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        self.db.execute(
            "DELETE FROM member_blocks WHERE blocker_profile_id=? AND blocked_profile_id=?",
            (actor["profile_id"], target["profile_id"]),
        )
        return {"ok": True, "blocked": False}

    # -- friends -----------------------------------------------------------
    def _friendship_row(self, a: str, b: str):
        lo, hi = _pair(a, b)
        return self.db.query_one(
            "SELECT * FROM friendships WHERE member_a_id=? AND member_b_id=?", (lo, hi),
        )

    def request_friend(self, user, handle: str) -> dict:
        actor = self.ensure_profile(user)
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        if actor["profile_id"] == target["profile_id"]:
            raise ValidationError("cannot friend yourself", "self_friend")
        if self._is_blocked(actor["profile_id"], target["profile_id"]):
            raise ForbiddenError("cannot send this request", "blocked")
        existing = self._friendship_row(actor["profile_id"], target["profile_id"])
        if existing and existing["status"] == "accepted":
            return {"ok": True, "status": "accepted", "friendship_id": existing["friendship_id"]}
        if existing and existing["status"] == "pending":
            return {"ok": True, "status": "pending", "friendship_id": existing["friendship_id"]}
        lo, hi = _pair(actor["profile_id"], target["profile_id"])
        fid = _id("frn")
        if existing:
            self.db.execute(
                "UPDATE friendships SET status='pending', requested_by=?, created_at=?, accepted_at=NULL "
                "WHERE friendship_id=?",
                (actor["profile_id"], _now(), existing["friendship_id"]),
            )
            fid = existing["friendship_id"]
        else:
            self.db.execute(
                "INSERT INTO friendships VALUES (?,?,?,?,?,?,?)",
                (fid, lo, hi, "pending", actor["profile_id"], _now(), None),
            )
        self._notify(target["profile_id"], "friend_request", actor["profile_id"], "profile", actor["profile_id"])
        return {"ok": True, "status": "pending", "friendship_id": fid}

    def accept_friend(self, user, handle: str) -> dict:
        actor = self.ensure_profile(user)
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        row = self._friendship_row(actor["profile_id"], target["profile_id"])
        if not row or row["status"] != "pending":
            raise ConflictError("no pending request", "no_friend_request")
        if row["requested_by"] == actor["profile_id"]:
            raise ForbiddenError("cannot accept your own request", "friend_forbidden")
        self.db.execute(
            "UPDATE friendships SET status='accepted', accepted_at=? WHERE friendship_id=?",
            (_now(), row["friendship_id"]),
        )
        self._notify(target["profile_id"], "friend_accepted", actor["profile_id"], "profile", actor["profile_id"])
        return {"ok": True, "status": "accepted", "friendship_id": row["friendship_id"]}

    def unfriend(self, user, handle: str) -> dict:
        actor = self.ensure_profile(user)
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        lo, hi = _pair(actor["profile_id"], target["profile_id"])
        self.db.execute("DELETE FROM friendships WHERE member_a_id=? AND member_b_id=?", (lo, hi))
        return {"ok": True, "status": "none"}

    def _friend_ids(self, profile_id: str) -> set[str]:
        rows = self.db.query(
            "SELECT member_a_id, member_b_id FROM friendships WHERE status='accepted' "
            "AND (member_a_id=? OR member_b_id=?)",
            (profile_id, profile_id),
        )
        ids = set()
        for row in rows:
            ids.add(row["member_a_id"] if row["member_b_id"] == profile_id else row["member_b_id"])
        return ids

    def friends_activity(self, user) -> dict:
        actor = self.ensure_profile(user)
        friend_ids = self._friend_ids(actor["profile_id"])
        items = []
        if not friend_ids:
            return {"items": items}
        placeholders = ",".join("?" * len(friend_ids))
        settings = {
            r["profile_id"]: r
            for r in self.db.query(
                f"SELECT * FROM member_settings WHERE profile_id IN ({placeholders})",
                tuple(friend_ids),
            )
        }
        profiles = {
            r["profile_id"]: r
            for r in self.db.query(
                f"SELECT * FROM profiles WHERE profile_id IN ({placeholders})",
                tuple(friend_ids),
            )
        }
        sessions = self.db.query(
            "SELECT vs.user_id, vs.event_id, vs.started_at FROM view_sessions vs "
            "WHERE vs.state='open' ORDER BY vs.started_at DESC"
        )
        seen = set()
        for session in sessions:
            profile = self.db.query_one(
                "SELECT * FROM profiles WHERE user_id=?", (session["user_id"],)
            )
            if not profile or profile["profile_id"] not in friend_ids:
                continue
            if profile["profile_id"] in seen:
                continue
            pref = settings.get(profile["profile_id"])
            if not pref or not pref["show_watching_to_friends"]:
                continue
            seen.add(profile["profile_id"])
            event = None
            try:
                event = self.cp.get_event_row(session["event_id"])
            except Exception:
                pass
            items.append({
                "member_id": profile["user_id"],
                "profile_id": profile["profile_id"],
                "display_name": profile["display_name"],
                "avatar_url": profile["avatar"],
                "activity": "watching_live",
                "event_id": session["event_id"],
                "sport": (event["category"] if event else None),
            })
        return {"items": items}

    # -- notifications -----------------------------------------------------
    def list_notifications(self, user) -> dict:
        actor = self.ensure_profile(user)
        rows = self.db.query(
            "SELECT * FROM notifications WHERE profile_id=? ORDER BY created_at DESC LIMIT 50",
            (actor["profile_id"],),
        )
        unread = self.db.query_one(
            "SELECT COUNT(*) AS c FROM notifications WHERE profile_id=? AND read_at IS NULL",
            (actor["profile_id"],),
        )
        items = []
        for row in rows:
            actor_pub = None
            if row["actor_profile_id"]:
                try:
                    actor_pub = self.public_profile(
                        dict(self._row("profiles", "profile_id", row["actor_profile_id"])), user
                    )
                except Exception:
                    actor_pub = None
            items.append({
                "notification_id": row["notification_id"],
                "type": row["kind"],
                "actor": actor_pub,
                "object_type": row["subject_type"],
                "object_id": row["subject_id"],
                "created_at": row["created_at"],
                "read_at": row["read_at"],
            })
        return {"items": items, "unread_count": int(unread["c"] if unread else 0)}

    def mark_notification_read(self, user, notification_id: str) -> dict:
        actor = self.ensure_profile(user)
        row = self.db.query_one(
            "SELECT * FROM notifications WHERE notification_id=? AND profile_id=?",
            (notification_id, actor["profile_id"]),
        )
        if not row:
            raise NotFoundError("notification not found", "notification_not_found")
        self.db.execute(
            "UPDATE notifications SET read_at=? WHERE notification_id=?",
            (_now(), notification_id),
        )
        return {"ok": True}

    # -- moments / studio --------------------------------------------------
    def ingest_score_moment(self, event_id: str, scoreboard: dict, previous: dict | None = None) -> dict | None:
        scoreboard = scoreboard or {}
        if not isinstance(scoreboard, dict):
            scoreboard = loads(scoreboard, {}) if isinstance(scoreboard, str) else {}
        self.cp.get_event_row(event_id)
        rights = self.cp.current_rights(event_id)
        prior = previous if previous is not None else {}
        if isinstance(prior, str):
            prior = loads(prior, {})
        elif not isinstance(prior, dict):
            try:
                prior = dict(prior)
            except Exception:
                prior = {}
        home = int(scoreboard.get("home") or 0)
        away = int(scoreboard.get("away") or 0)
        prev_home = int(prior.get("home") or 0)
        prev_away = int(prior.get("away") or 0)
        delta = abs((home + away) - (prev_home + prev_away))
        if delta <= 0 and scoreboard.get("clock") == prior.get("clock"):
            return None
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - 8000
        end_ms = now_ms + 4000
        moment_type = "score" if delta else "clock"
        label = scoreboard.get("label") or (
            f"{scoreboard.get('period') or ''} {scoreboard.get('clock') or ''} "
            f"{home}–{away}"
        ).strip()
        signals = {
            "score_change": bool(delta),
            "score_delta": delta,
            "clock": scoreboard.get("clock"),
            "period": scoreboard.get("period"),
        }
        moment_id = _id("mom")
        status = "candidate"
        if rights and not rights["revoked"]:
            status = "publishable"
        else:
            status = "held"
        self.db.execute(
            "INSERT INTO detected_moments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                moment_id, event_id, start_ms, end_ms, moment_type, label[:120],
                0.7 if delta else 0.4, dumps(signals), status,
                rights["version"] if rights else None, _now(),
            ),
        )
        self.db.execute(
            "INSERT INTO moment_signals VALUES (?,?,?,?,?,?)",
            (_id("sig"), moment_id, "scoreboard", float(delta), dumps(signals), _now()),
        )
        if status == "publishable":
            self.cp._outbox(event_id, "moment.published", {
                "moment_id": moment_id, "label": label, "start_ms": start_ms, "end_ms": end_ms,
                "type": moment_type,
            })
        return {"moment_id": moment_id, "status": status}

    def list_event_moments(self, user, event_id: str) -> dict:
        self.cp.get_event_row(event_id)
        decision = self._event_access(user, event_id)
        if decision and not decision["allow"] and not self._staff(user):
            raise ForbiddenError("not authorized for this event", "event_forbidden")
        rows = self.db.query(
            "SELECT * FROM detected_moments WHERE event_id=? AND status='publishable' "
            "ORDER BY start_ms DESC",
            (event_id,),
        )
        return {"moments": [self._moment_public(r) for r in rows]}

    def event_timeline(self, user, event_id: str) -> dict:
        event = self.cp.get_event_row(event_id)
        decision = self._event_access(user, event_id)
        if decision and not decision["allow"] and not self._staff(user):
            raise ForbiddenError("not authorized for this event", "event_forbidden")
        duration_ms = 0
        game = self.db.query_one(
            "SELECT duration_seconds FROM games WHERE event_id=? AND duration_seconds IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (event_id,),
        )
        if game and game["duration_seconds"]:
            duration_ms = int(float(game["duration_seconds"]) * 1000)
        rows = self.db.query(
            "SELECT * FROM detected_moments WHERE event_id=? AND status IN ('publishable','candidate') "
            "ORDER BY start_ms ASC",
            (event_id,),
        )
        return {
            "event_id": event_id,
            "duration_ms": duration_ms,
            "moments": [self._moment_public(r) for r in rows],
        }

    @staticmethod
    def _moment_public(row) -> dict:
        return {
            "moment_id": row["moment_id"],
            "event_id": row["event_id"],
            "start_ms": row["start_ms"],
            "end_ms": row["end_ms"],
            "type": row["moment_type"],
            "label": row["label"],
            "confidence": row["confidence"],
            "signals": loads(row["signals"], {}),
            "status": row["status"],
        }

    def studio_sources(self, user) -> dict:
        profile = self.ensure_profile(user)
        games = []
        for row in self.db.query(
            "SELECT * FROM games WHERE processing_status='ready' ORDER BY created_at DESC LIMIT 50"
        ):
            game = dict(row)
            if not self.can_see_game(user, game):
                continue
            if not game.get("media_asset_id") or not game.get("duration_seconds"):
                continue
            games.append({
                "game_id": game["game_id"],
                "event_id": game["event_id"],
                "title": f"{game['home_team_name']} vs {game['away_team_name']}",
                "sport": game["sport"],
                "duration_seconds": game["duration_seconds"],
                "rights_version": game["rights_version"],
                "source_media_asset_id": game["media_asset_id"],
            })
        live = []
        for event in self.portal.live(user):
            if event["status"] in ("live", "replay", "archive"):
                live.append({
                    "event_id": event["event_id"],
                    "title": event["title"],
                    "sport": event.get("category"),
                    "status": event["status"],
                    "scoreboard": event.get("scoreboard") or {},
                })
        return {"games": games, "events": live, "profile_id": profile["profile_id"]}

    # -- watch parties -----------------------------------------------------
    def create_watch_party(self, user, data: dict) -> dict:
        data = data or {}
        event_id = data.get("event_id") or ""
        self.cp.get_event_row(event_id)
        decision = self._event_access(user, event_id)
        if decision and not decision["allow"]:
            raise ForbiddenError("not authorized for this event", "event_forbidden")
        visibility = data.get("visibility") or "friends"
        if visibility not in PARTY_VISIBILITY:
            raise ValidationError("visibility must be friends or invite", "bad_visibility")
        profile = self.ensure_profile(user)
        party_id = _id("party")
        code = (event_id.replace("evt_", "")[:5] + "-" + uuid.uuid4().hex[:3]).upper()
        self.db.execute(
            "INSERT INTO watch_parties VALUES (?,?,?,?,?,?,?)",
            (party_id, event_id, profile["profile_id"], visibility, code, "open", _now()),
        )
        self.db.execute(
            "INSERT INTO watch_party_members VALUES (?,?,?,?)",
            (party_id, profile["profile_id"], _now(), None),
        )
        self.cp._outbox(party_id, "member.joined", {
            "party_id": party_id, "profile_id": profile["profile_id"], "event_id": event_id,
        })
        return {"party_id": party_id, "join_code": code, "event_id": event_id, "visibility": visibility}

    def join_watch_party(self, user, party_id: str) -> dict:
        party = dict(self._row("watch_parties", "party_id", party_id, "party not found", "party_not_found"))
        if party["status"] != "open":
            raise ConflictError("party is closed", "party_closed")
        profile = self.ensure_profile(user)
        if party["visibility"] == "friends":
            host = party["host_profile_id"]
            if profile["profile_id"] != host and profile["profile_id"] not in self._friend_ids(host):
                raise ForbiddenError("friends-only party", "party_forbidden")
        decision = self._event_access(user, party["event_id"])
        if decision and not decision["allow"]:
            raise ForbiddenError("not authorized for this event", "event_forbidden")
        self.db.execute(
            "INSERT OR IGNORE INTO watch_party_members VALUES (?,?,?,?)",
            (party_id, profile["profile_id"], _now(), None),
        )
        self.db.execute(
            "UPDATE watch_party_members SET left_at=NULL WHERE party_id=? AND profile_id=?",
            (party_id, profile["profile_id"]),
        )
        self.cp._outbox(party_id, "member.joined", {
            "party_id": party_id, "profile_id": profile["profile_id"],
        })
        return {"ok": True, "party_id": party_id, "event_id": party["event_id"]}

    def post_watch_party_message(self, user, party_id: str, data: dict) -> dict:
        party = dict(self._row("watch_parties", "party_id", party_id, "party not found", "party_not_found"))
        profile = self.ensure_profile(user)
        member = self.db.query_one(
            "SELECT 1 FROM watch_party_members WHERE party_id=? AND profile_id=? AND left_at IS NULL",
            (party_id, profile["profile_id"]),
        )
        if not member:
            raise ForbiddenError("not in this party", "party_forbidden")
        kind = (data or {}).get("kind") or "comment"
        if kind not in ("comment", "reaction"):
            raise ValidationError("kind must be comment or reaction", "bad_message_kind")
        body = _safe_text((data or {}).get("body") or "", 280)
        mid = _id("wpm")
        self.db.execute(
            "INSERT INTO watch_party_messages VALUES (?,?,?,?,?,?)",
            (mid, party_id, profile["profile_id"], kind, body, _now()),
        )
        event_type = "comment.created" if kind == "comment" else "reaction.created"
        self.cp._outbox(party_id, event_type, {
            "party_id": party_id, "message_id": mid, "kind": kind, "body": body,
            "profile_id": profile["profile_id"], "event_id": party["event_id"],
        })
        return {"message_id": mid, "kind": kind, "body": body}

    def watch_party_view(self, user, party_id: str) -> dict:
        party = dict(self._row("watch_parties", "party_id", party_id, "party not found", "party_not_found"))
        profile = self.ensure_profile(user)
        member = self.db.query_one(
            "SELECT 1 FROM watch_party_members WHERE party_id=? AND profile_id=?",
            (party_id, profile["profile_id"]),
        )
        if not member and not self._staff(user):
            raise ForbiddenError("not in this party", "party_forbidden")
        members = self.db.query(
            "SELECT m.profile_id, p.display_name, p.handle FROM watch_party_members m "
            "JOIN profiles p ON p.profile_id=m.profile_id WHERE m.party_id=? AND m.left_at IS NULL",
            (party_id,),
        )
        return {
            "party_id": party["party_id"],
            "event_id": party["event_id"],
            "join_code": party["join_code"],
            "visibility": party["visibility"],
            "status": party["status"],
            "members": [dict(r) for r in members],
        }

    # -- share / moment page -----------------------------------------------
    def copy_link_share(self, user, post_id: str, destination: str = "copy_link") -> dict:
        post = self.require_post(user, post_id)
        if destination != "copy_link":
            raise ForbiddenError("that destination is not enabled", "share_destination_unavailable")
        clip_id = post.get("clip_id")
        path = f"/moment/{clip_id}" if clip_id else f"/post/{post_id}"
        base = (self.cp.config.public_app_url or self.cp.config.public_base_url or "").rstrip("/")
        url = f"{base}{path}" if base else path
        self._audit("POST_SHARE_LINK", post_id, "member", user["user_id"],
                    {"destination": destination, "url": url})
        return {"ok": True, "destination": destination, "url": url}

    def public_moment(self, viewer, clip_id: str) -> dict:
        clip = dict(self._row("clips", "clip_id", clip_id, "clip not found", "clip_not_found"))
        available = self.clip_media_available(viewer, clip)
        provenance = self.clip_provenance(viewer, clip)
        media_url = None
        if available and clip.get("derived_media_asset_id"):
            media_url = f"/api/network/media/{clip['derived_media_asset_id']}"
        return {
            "clip_id": clip_id,
            "available": available,
            "message": None if available else "This moment is no longer available.",
            "caption": clip.get("caption"),
            "sport": clip.get("sport"),
            "provenance": provenance,
            "media_url": media_url,
            "source": {
                "event_id": provenance.get("event_id"),
                "rights_version": provenance.get("rights_version"),
                "start_ms": int((clip.get("start_seconds") or 0) * 1000),
                "end_ms": int((clip.get("end_seconds") or 0) * 1000),
            },
        }

    def clip_media_available(self, viewer, clip) -> bool:
        if clip["publication_status"] in ("removed", "restricted"):
            return False
        if not clip.get("source_game_id"):
            return True
        try:
            game = dict(self._row("games", "game_id", clip["source_game_id"]))
        except NotFoundError:
            return False
        if game["verification_status"] in ("rejected", "rights_restricted"):
            return False
        if clip.get("source_rights_version") is not None and game.get("event_id"):
            rights = self.cp.current_rights(game["event_id"])
            if not rights or rights["revoked"] or rights["version"] != clip["source_rights_version"]:
                return False
            decision = self._event_access(viewer, game["event_id"]) if viewer else None
            if decision and not decision["allow"]:
                return False
        return True

    def restrict_derived_from_event(self, event_id: str, operator) -> dict:
        games = self.db.query("SELECT game_id FROM games WHERE event_id=?", (event_id,))
        clip_ids = []
        post_ids = []
        for game in games:
            clips = self.db.query("SELECT * FROM clips WHERE source_game_id=?", (game["game_id"],))
            for raw in clips:
                clip = dict(raw)
                clip_ids.append(clip["clip_id"])
                self.db.execute(
                    "UPDATE clips SET rights_decision='revoked', updated_at=? WHERE clip_id=?",
                    (_now(), clip["clip_id"]),
                )
                if clip.get("post_id"):
                    post_ids.append(clip["post_id"])
        self.cp._outbox(event_id, "rights.revoked", {"derived_clips": clip_ids})
        self._moten_handoff("clip-withdrawn", event_id, {
            "schema": "three-zone.moten.clip-withdrawn.v1",
            "source_system": "three-zone-mvp",
            "handoff_type": "clip-withdrawn",
            "event_id": event_id,
            "clip_ids": clip_ids,
            "post_ids": post_ids,
            "publication_decision": "unavailable",
        })
        return {"clips": clip_ids, "posts": post_ids}

    def _moten_handoff(self, handoff_type: str, source_object_id: str, payload: dict) -> dict:
        from .moten_adapter import MotenIntakeService
        moten = getattr(self, "moten", None) or MotenIntakeService(self.cp)
        return moten.enqueue_runtime(handoff_type, source_object_id, payload)

    def _feed_score(self, viewer, actor, post, following, friend_ids, team_ids, live_event_ids) -> float:
        score = 0.0
        published = float(post.get("published_at") or post.get("created_at") or 0)
        age_hours = max(0.0, (_now() - published) / 3600.0) if published else 48.0
        score += max(0.0, 24.0 - age_hours)
        if actor and post["author_profile_id"] == actor["profile_id"]:
            score += 4.0
        if post["author_profile_id"] in following:
            score += 12.0
        if post["author_profile_id"] in friend_ids:
            score += 10.0
        tags = self.db.query(
            "SELECT team_id FROM team_tags WHERE subject_type='post' AND subject_id=?",
            (post["post_id"],),
        )
        if any(t["team_id"] in team_ids for t in tags):
            score += 14.0
        if actor:
            author = self.db.query_one(
                "SELECT market FROM profiles WHERE profile_id=?", (post["author_profile_id"],)
            )
            if author and author["market"] == actor["market"]:
                score += 6.0
        event_id = post.get("event_id")
        if not event_id and post.get("clip_id"):
            clip = self.db.query_one("SELECT source_game_id FROM clips WHERE clip_id=?", (post["clip_id"],))
            if clip and clip["source_game_id"]:
                game = self.db.query_one("SELECT event_id FROM games WHERE game_id=?", (clip["source_game_id"],))
                event_id = game["event_id"] if game else None
        if event_id and event_id in live_event_ids:
            score += 20.0
        likes, comments = self._counts("post", post["post_id"])
        score += min(8.0, (likes + comments) / 20.0)
        recent = self.db.query_one(
            "SELECT COUNT(*) AS c FROM posts WHERE author_profile_id=? AND publication_status='published' "
            "AND post_id!=? AND COALESCE(published_at, created_at) > ?",
            (post["author_profile_id"], post["post_id"], published - 7200.0),
        )
        dupes = int(recent["c"] if recent else 0)
        score -= min(6.0, dupes * 2.0)
        return score

    def enrich_search(self, user, query: str) -> list[dict]:
        results = list(self.portal.search(user, query))
        term = (query or "").strip().lower()
        if len(term) < 2:
            return results
        q = "%" + term + "%"
        for row in self.db.query(
            "SELECT handle, display_name, profile_id FROM profiles "
            "WHERE visibility='public' AND (lower(handle) LIKE ? OR lower(display_name) LIKE ?) LIMIT 8",
            (q, q),
        ):
            results.append({
                "id": row["profile_id"], "name": row["display_name"],
                "kind": "person", "handle": row["handle"],
            })
        for row in self.db.query(
            "SELECT post_id, caption, sport FROM posts WHERE publication_status='published' "
            "AND lower(caption) LIKE ? LIMIT 8",
            (q,),
        ):
            results.append({
                "id": row["post_id"], "name": row["caption"][:80] or row["sport"],
                "kind": "clip" if False else "post", "sport": row["sport"],
            })
        return results[:40]
