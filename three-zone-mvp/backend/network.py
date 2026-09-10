"""Member sports network: profiles, posts, games, clips, and social graph.

Identity stays on ``users``. Public surfaces use ``profiles``. Visibility goes
through :meth:`NetworkService.can_see_post` (and game/clip siblings). Event-bound
media calls ``ControlPlane.evaluate_access``. Social facts are published to
``socket_outbox`` for a future bus. UGC storage goes through ``media_provider``.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
import uuid

from .control_plane import (
    AuthError, ConflictError, ControlError, ForbiddenError, NotFoundError, ValidationError,
)
from .db import dumps, loads
from .media_provider import ProviderError
from .huddle import HuddleExtensions


class RateLimitError(ControlError):
    status = 429


PROFILE_TYPES = {
    "athlete", "parent", "coach", "fan", "school", "team",
    "videographer", "sports_organization",
}
SPORTS = {"basketball", "football", "soccer", "baseball", "volleyball", "other"}
VISIBILITY = {"private", "connections", "team", "public"}
PUBLICATION = {"draft", "processing", "published", "restricted", "removed"}
LEVELS = {"youth", "middle_school", "high_school", "aau_club", "college", "other"}
SOURCE_TYPES = {"three_zone_capture", "member_upload", "school_upload", "partner_feed", "other"}
UPLOAD_STATES = {
    "created", "authorized", "uploading", "uploaded", "processing",
    "ready", "failed", "quarantined", "expired",
}
HANDLE_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
SPORTS_WORDS = {
    "basketball", "football", "soccer", "baseball", "volleyball", "hockey",
    "lacrosse", "game", "clip", "athlete", "team", "coach", "tournament",
}
PROHIBITED_WORDS = {"csam", "exploit-kit"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


def _safe_text(value: str, limit: int = 2000) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise ValidationError(f"text exceeds {limit} characters", "text_too_long")
    return text


def encode_cursor(published_at, post_id: str) -> str:
    return f"{published_at}:{post_id}"


def decode_cursor(cursor: str | None):
    if not cursor:
        return None
    try:
        ts, post_id = cursor.split(":", 1)
        return float(ts), post_id
    except (ValueError, TypeError):
        raise ValidationError("invalid cursor", "bad_cursor")


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        now = _now()
        bucket = [t for t in self._hits.get(key, []) if now - t < window]
        if len(bucket) >= limit:
            raise RateLimitError("too many requests", "rate_limited")
        bucket.append(now)
        self._hits[key] = bucket


class NetworkService(HuddleExtensions):
    def __init__(self, cp, portal, provider, photo_storage=None):
        self.cp = cp
        self.portal = portal
        self.db = cp.db
        self.provider = provider
        self.photo_storage = photo_storage
        if self.photo_storage is None:
            from .photo_storage import FakePhotoStorage
            self.photo_storage = FakePhotoStorage(
                webhook_secret=getattr(cp.config, "fake_webhook_secret", "fake-webhook-secret"),
            )
        self.limiter = RateLimiter()

    # -- helpers -----------------------------------------------------------
    def _audit(self, event_type, subject_id=None, actor_type="member", actor_id="system",
               payload=None, rights_version=None):
        return self.portal.audit(
            event_type, subject_id=subject_id, actor_type=actor_type, actor_id=actor_id,
            payload=payload or {}, rights_version=rights_version,
        )

    def _outbox(self, subject_id: str, type_: str, payload: dict) -> None:
        self.cp._outbox(subject_id or "network", type_, payload)

    def _staff(self, user) -> bool:
        return bool(user and user.get("role") in ("operator", "owner", "admin"))

    def _owner(self, user) -> bool:
        return bool(user and user.get("role") in ("owner", "admin"))

    def _row(self, table: str, key: str, value: str, err="not_found", code="not_found"):
        row = self.db.query_one(f"SELECT * FROM {table} WHERE {key}=?", (value,))
        if not row:
            raise NotFoundError(err, code)
        return row

    def _notify(self, profile_id, kind, actor_profile_id, subject_type, subject_id):
        if not profile_id or profile_id == actor_profile_id:
            return
        self.db.execute(
            "INSERT INTO notifications VALUES (?,?,?,?,?,?,?,?)",
            (_id("ntf"), profile_id, kind, actor_profile_id, subject_type, subject_id, _now(), None),
        )

    def check_auth_rate(self, client_key: str) -> None:
        self.limiter.check(f"auth:{client_key or 'unknown'}", 8)

    def check_login_rate(self, client_key: str) -> None:
        self.check_auth_rate(client_key)

    def check_register_rate(self, client_key: str) -> None:
        self.check_auth_rate(client_key)

    def check_staff_rate(self, actor_id: str) -> None:
        self.limiter.check(f"staff:{actor_id or 'unknown'}", 10)

    def _parse_tag_list(self, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(part).strip() for part in value if str(part).strip()]

    def _resolve_tag_inputs(self, data: dict) -> tuple[list[str], list[str]]:
        ids = []
        for raw in self._parse_tag_list(data.get("tagged_profile_ids")) + self._parse_tag_list(
            data.get("tagged_handles")
        ):
            handle = raw.lower().lstrip("@")
            row = self.db.query_one(
                "SELECT profile_id FROM profiles WHERE profile_id=? OR handle=?",
                (raw, handle),
            )
            if row:
                ids.append(row["profile_id"])
        teams = self._parse_tag_list(data.get("tagged_team_ids") or data.get("tagged_teams"))
        return ids, teams

    def _tag(self, subject_type, subject_id, profile_ids=None, team_ids=None):
        for pid in profile_ids or []:
            if pid:
                self.db.execute(
                    "INSERT OR IGNORE INTO athlete_tags VALUES (?,?,?)",
                    (subject_type, subject_id, pid),
                )
                self._notify(pid, "tag", None, subject_type, subject_id)
        for tid in team_ids or []:
            if tid:
                self.db.execute(
                    "INSERT OR IGNORE INTO team_tags VALUES (?,?,?)",
                    (subject_type, subject_id, tid),
                )

    def _post_tags(self, post_id: str) -> dict:
        athletes = []
        for row in self.db.query(
            "SELECT p.handle, p.display_name FROM athlete_tags t "
            "JOIN profiles p ON p.profile_id=t.profile_id "
            "WHERE t.subject_type='post' AND t.subject_id=?",
            (post_id,),
        ):
            athletes.append({"handle": row["handle"], "display_name": row["display_name"]})
        teams = [
            row["team_id"]
            for row in self.db.query(
                "SELECT team_id FROM team_tags WHERE subject_type='post' AND subject_id=?",
                (post_id,),
            )
        ]
        return {"athlete_tags": athletes, "team_tags": teams}

    def _counts(self, subject_type, subject_id):
        likes = self.db.query_one(
            "SELECT COUNT(*) AS c FROM reactions WHERE subject_type=? AND subject_id=? AND kind='like'",
            (subject_type, subject_id),
        )
        comments = self.db.query_one(
            "SELECT COUNT(*) AS c FROM comments WHERE subject_type=? AND subject_id=? AND deleted_at IS NULL",
            (subject_type, subject_id),
        )
        return int(likes["c"] if likes else 0), int(comments["c"] if comments else 0)

    def _follows(self, follower_id, followed_id) -> bool:
        if not follower_id or not followed_id:
            return False
        return bool(self.db.query_one(
            "SELECT 1 FROM follows WHERE follower_profile_id=? AND followed_profile_id=?",
            (follower_id, followed_id),
        ))

    def _same_team(self, viewer_profile, team_id) -> bool:
        if not viewer_profile or not team_id:
            return False
        if viewer_profile["team_id"] == team_id:
            return True
        return bool(self.db.query_one(
            "SELECT 1 FROM team_tags WHERE team_id=? AND subject_type='profile' AND subject_id=?",
            (team_id, viewer_profile["profile_id"]),
        ))

    def _event_access(self, viewer, event_id):
        if not event_id:
            return None
        if not viewer:
            return {"allow": False, "code": "authentication_required"}
        try:
            row = self.cp.get_event_row(event_id)
        except NotFoundError:
            return {"allow": False, "code": "event_not_found"}
        return self.cp.evaluate_access(viewer, row)

    def _classify(self, caption: str, sport: str) -> str:
        text = f"{caption} {sport}".lower()
        if any(word in text for word in PROHIBITED_WORDS):
            return "needs_review"
        if sport in SPORTS - {"other"} or any(word in text for word in SPORTS_WORDS):
            return "sports"
        if sport == "other":
            return "probably_sports"
        return "not_sports"

    def _flag(self, subject_type, subject_id, result, source="classifier", reporter=None, reason=""):
        if result in ("sports",):
            return None
        self.db.execute(
            "INSERT INTO moderation_cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_id("mod"), subject_type, subject_id, reporter, source, result,
             None, None, reason, None, 0, _now(), None),
        )
        return result

    # -- profiles ----------------------------------------------------------
    def ensure_profile(self, user, profile_type: str = "fan"):
        row = self.db.query_one("SELECT * FROM profiles WHERE user_id=?", (user["user_id"],))
        if row:
            return dict(row)
        handle = re.sub(r"[^a-z0-9_]", "", (user["user_id"] or "member").lower()) or "member"
        if not HANDLE_RE.match(handle):
            handle = "m_" + uuid.uuid4().hex[:10]
        taken = self.db.query_one("SELECT 1 FROM profiles WHERE handle=?", (handle,))
        if taken:
            handle = f"{handle}_{uuid.uuid4().hex[:4]}"
        if profile_type not in PROFILE_TYPES:
            profile_type = "fan"
        zones = user.get("zones") or ["midwest"]
        market = "midwest" if "*" in zones else (zones[0] if zones else "midwest")
        stamp = _now()
        profile_id = _id("prf")
        self.db.execute(
            "INSERT INTO profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (profile_id, user["user_id"], handle, user["display_name"], "", "",
             market, dumps([]), profile_type, "public", "none", "", None, stamp, stamp),
        )
        self._audit("PROFILE_CREATED", profile_id, "member", user["user_id"],
                    {"handle": handle, "profile_type": profile_type})
        return dict(self._row("profiles", "profile_id", profile_id))

    def public_profile(self, profile, viewer=None) -> dict:
        badge = profile["verification_badge"] if profile["verification_state"] == "verified" else ""
        return {
            "profile_id": profile["profile_id"],
            "handle": profile["handle"],
            "display_name": profile["display_name"],
            "avatar": profile["avatar"],
            "bio": profile["bio"],
            "market": profile["market"],
            "sports": loads(profile["sports"], []),
            "profile_type": profile["profile_type"],
            "visibility": profile["visibility"],
            "verification_state": profile["verification_state"],
            "verification_badge": badge,
            "created_at": profile["created_at"],
        }

    def get_profile_by_handle(self, handle: str, viewer=None) -> dict:
        profile = dict(self._row("profiles", "handle", (handle or "").lower(), "profile not found", "profile_not_found"))
        if profile["visibility"] == "private":
            owner = viewer and self.ensure_profile(viewer)["profile_id"] == profile["profile_id"]
            if not owner and not self._staff(viewer):
                raise ForbiddenError("profile is private", "profile_private")
        return self.public_profile(profile, viewer)

    def get_own_profile(self, user) -> dict:
        profile = self.ensure_profile(user)
        public = self.public_profile(profile, user)
        public["user_role"] = user["role"]
        return public

    def update_own_profile(self, user, data: dict) -> dict:
        profile = self.ensure_profile(user)
        data = data or {}
        handle = (data.get("handle") or profile["handle"]).strip().lower()
        if not HANDLE_RE.match(handle):
            raise ValidationError("handle must be 3–32 lowercase letters", "bad_handle")
        other = self.db.query_one("SELECT profile_id FROM profiles WHERE handle=?", (handle,))
        if other and other["profile_id"] != profile["profile_id"]:
            raise ConflictError("handle is not available", "handle_taken")
        profile_type = data.get("profile_type") or profile["profile_type"]
        if profile_type not in PROFILE_TYPES:
            raise ValidationError("unsupported profile type", "bad_profile_type")
        if data.get("verification_badge") or data.get("verification_state") == "verified":
            raise ForbiddenError("members cannot self-assign a verified badge", "badge_forbidden")
        sports = data.get("sports")
        if sports is not None:
            if not isinstance(sports, list) or any(s not in SPORTS for s in sports):
                raise ValidationError("invalid sports list", "bad_sports")
        else:
            sports = loads(profile["sports"], [])
        visibility = data.get("visibility") or profile["visibility"]
        if visibility not in VISIBILITY:
            raise ValidationError("invalid visibility", "bad_visibility")
        market = data.get("market") or profile["market"]
        if market not in ("midwest", "west", "east"):
            raise ValidationError("market must be a configured zone", "bad_market")
        self.db.execute(
            "UPDATE profiles SET handle=?, display_name=?, avatar=?, bio=?, market=?, sports=?,"
            " profile_type=?, visibility=?, team_id=?, updated_at=? WHERE profile_id=?",
            (
                handle, _safe_text(data.get("display_name") or profile["display_name"], 80),
                _safe_text(data.get("avatar") or profile["avatar"], 200),
                _safe_text(data.get("bio") if "bio" in data else profile["bio"], 280),
                market, dumps(sports), profile_type, visibility,
                data.get("team_id", profile["team_id"]), _now(), profile["profile_id"],
            ),
        )
        return self.get_own_profile(user)

    def set_verification(self, operator, profile_id: str, badge: str, state: str = "verified"):
        self.cp.require_operator(operator)
        if badge not in ("", "verified_athlete", "verified_team"):
            raise ValidationError("unsupported badge", "bad_badge")
        if state not in ("none", "verified"):
            raise ValidationError("unsupported verification state", "bad_verification")
        self._row("profiles", "profile_id", profile_id, "profile not found", "profile_not_found")
        self.db.execute(
            "UPDATE profiles SET verification_state=?, verification_badge=?, updated_at=? WHERE profile_id=?",
            (state, badge if state == "verified" else "", _now(), profile_id),
        )
        self._audit("PROFILE_VERIFICATION_CHANGED", profile_id, "operator", operator["user_id"],
                    {"state": state, "badge": badge})
        return self.public_profile(dict(self._row("profiles", "profile_id", profile_id)), operator)

    def follow(self, user, handle: str) -> dict:
        actor = self.ensure_profile(user)
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        if actor["profile_id"] == target["profile_id"]:
            raise ValidationError("cannot follow yourself", "self_follow")
        self.db.execute(
            "INSERT OR IGNORE INTO follows VALUES (?,?,?)",
            (actor["profile_id"], target["profile_id"], _now()),
        )
        self._audit("FOLLOW_CREATED", target["profile_id"], "member", user["user_id"])
        self._outbox(target["profile_id"], "network.follow", {
            "follower": actor["profile_id"], "followed": target["profile_id"],
        })
        self._notify(target["profile_id"], "follow", actor["profile_id"], "profile", target["profile_id"])
        return {"ok": True, "following": True}

    def unfollow(self, user, handle: str) -> dict:
        actor = self.ensure_profile(user)
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        self.db.execute(
            "DELETE FROM follows WHERE follower_profile_id=? AND followed_profile_id=?",
            (actor["profile_id"], target["profile_id"]),
        )
        return {"ok": True, "following": False}

    # -- visibility PDP ----------------------------------------------------
    def _visibility_allows(self, viewer, author_profile_id, visibility, team_id=None) -> bool:
        if visibility == "public":
            return True
        if not viewer:
            return False
        if self._staff(viewer):
            return True
        actor = self.ensure_profile(viewer)
        if actor["profile_id"] == author_profile_id:
            return True
        if visibility == "private":
            return False
        if visibility == "connections":
            return (
                self._follows(actor["profile_id"], author_profile_id)
                or self._follows(author_profile_id, actor["profile_id"])
            )
        if visibility == "team":
            return self._same_team(actor, team_id)
        return False

    def can_see_post(self, viewer, post) -> bool:
        """Sibling PDP: may this member see this post?

        Event-bound posts cannot exceed ``evaluate_access``. Client flags are ignored.
        """
        status = post["publication_status"]
        if status == "removed":
            return self._staff(viewer)
        if status in ("draft", "processing"):
            return bool(viewer and (
                self._staff(viewer) or self.ensure_profile(viewer)["profile_id"] == post["author_profile_id"]
            ))
        if status == "restricted":
            return bool(viewer and (
                self._staff(viewer) or self.ensure_profile(viewer)["profile_id"] == post["author_profile_id"]
            ))
        tags = self.db.query("SELECT team_id FROM team_tags WHERE subject_type='post' AND subject_id=?",
                             (post["post_id"],))
        team_id = tags[0]["team_id"] if tags else None
        if not self._visibility_allows(viewer, post["author_profile_id"], post["visibility"], team_id):
            return False
        if post.get("clip_id"):
            try:
                clip = dict(self._row("clips", "clip_id", post["clip_id"]))
            except NotFoundError:
                return False
            if clip["publication_status"] == "removed":
                return self._staff(viewer)
            return self._visibility_allows(viewer, clip["creator_profile_id"], clip["visibility"])
        if post.get("event_id"):
            decision = self._event_access(viewer, post["event_id"])
            if decision and not decision["allow"]:
                return False
        return True

    def can_see_game(self, viewer, game) -> bool:
        if game["processing_status"] == "quarantined":
            return self._staff(viewer)
        if game["verification_status"] in ("rejected", "rights_restricted"):
            return bool(viewer and (
                self._staff(viewer) or self.ensure_profile(viewer)["profile_id"] == game["uploader_profile_id"]
            ))
        if not self._visibility_allows(viewer, game["uploader_profile_id"], game["visibility"],
                                      game.get("home_team_id")):
            return False
        if game.get("event_id"):
            decision = self._event_access(viewer, game["event_id"])
            if decision and not decision["allow"]:
                return False
        return True

    def can_see_clip(self, viewer, clip) -> bool:
        if clip["publication_status"] == "removed":
            return self._staff(viewer)
        if clip["publication_status"] in ("draft", "rendering", "failed"):
            return bool(viewer and (
                self._staff(viewer) or self.ensure_profile(viewer)["profile_id"] == clip["creator_profile_id"]
            ))
        if clip.get("source_game_id"):
            try:
                game = dict(self._row("games", "game_id", clip["source_game_id"]))
            except NotFoundError:
                return False
            if game["verification_status"] in ("rejected", "rights_restricted"):
                return self._staff(viewer)
            if not self.can_see_game(viewer, game):
                return False
            if clip.get("source_rights_version") is not None and game.get("event_id"):
                rights = self.cp.current_rights(game["event_id"])
                if not rights or rights["version"] != clip["source_rights_version"] or rights["revoked"]:
                    return False
                decision = self._event_access(viewer, game["event_id"])
                if decision and not decision["allow"]:
                    return False
        return self._visibility_allows(viewer, clip["creator_profile_id"], clip["visibility"])

    def require_post(self, viewer, post_id):
        post = dict(self._row("posts", "post_id", post_id, "post not found", "post_not_found"))
        if not self.can_see_post(viewer, post):
            raise ForbiddenError("not authorized to view this post", "post_forbidden")
        return post

    def require_game(self, viewer, game_id):
        game = dict(self._row("games", "game_id", game_id, "game not found", "game_not_found"))
        if not self.can_see_game(viewer, game):
            raise ForbiddenError("not authorized to view this game", "game_forbidden")
        return game

    def require_clip(self, viewer, clip_id):
        clip = dict(self._row("clips", "clip_id", clip_id, "clip not found", "clip_not_found"))
        if not self.can_see_clip(viewer, clip):
            raise ForbiddenError("not authorized to view this clip", "clip_forbidden")
        return clip

    def _adapter_for_kind(self, kind: str):
        if kind == "photo":
            return self.photo_storage
        return self.provider

    def _webhook_adapters(self):
        adapters = [self.provider]
        if self.photo_storage is not None:
            adapters.append(self.photo_storage)
        return adapters

    # -- uploads -----------------------------------------------------------
    def _safe_upload_contract(self, job, session) -> dict:
        url = session.get("upload_url") or job.get("upload_url") or ""
        method = session.get("upload_method") or job.get("upload_method")
        return {
            "upload_job_id": job["upload_job_id"],
            "upload_url": url,
            "expiry": session.get("expiry") or job.get("expires_at"),
            "upload_method": method,
            "resumable": bool(session.get("resumable") if "resumable" in session
                              else method == "tus"),
            "expected": {
                "kind": job["expected_kind"],
                "max_bytes": (
                    self.cp.config.max_game_bytes if job["expected_kind"] == "game"
                    else self.cp.config.max_photo_bytes if job["expected_kind"] == "photo"
                    else 80 * 1024 * 1024
                ),
                "max_duration_seconds": (
                    None if job["expected_kind"] in ("game", "photo")
                    else self.cp.config.max_post_video_seconds
                ),
            },
        }

    def create_upload(self, user, data: dict) -> dict:
        self.limiter.check(f"upload:{user['user_id']}", 20)
        kind = (data or {}).get("kind")
        if kind not in ("photo", "clip", "game"):
            raise ValidationError("kind must be photo, clip, or full game", "bad_kind")
        profile = self.ensure_profile(user)
        idem = (data.get("idempotency_key") or "").strip() or None
        if idem:
            existing = self.db.query_one(
                "SELECT * FROM upload_jobs WHERE owner_profile_id=? AND idempotency_key=?",
                (profile["profile_id"], idem),
            )
            if existing:
                session = {
                    "upload_url": existing["upload_url"] or "",
                    "expiry": existing["expires_at"],
                    "upload_method": existing["upload_method"],
                    "resumable": existing["upload_method"] == "tus",
                }
                return self._safe_upload_contract(dict(existing), session)
        active = self.db.query_one(
            "SELECT * FROM upload_jobs WHERE owner_profile_id=? AND intended_type=? "
            "AND status NOT IN ('ready','failed','expired','quarantined')",
            (profile["profile_id"], kind),
        )
        if active and not data.get("retry"):
            raise ConflictError("an upload is already in progress", "upload_in_progress")
        max_bytes = (
            self.cp.config.max_game_bytes if kind == "game"
            else self.cp.config.max_photo_bytes if kind == "photo"
            else 80 * 1024 * 1024
        )
        adapter = self._adapter_for_kind(kind)
        session = adapter.create_direct_upload(
            kind,
            max_bytes=max_bytes,
            max_duration_seconds=(
                None if kind in ("game", "photo") else self.cp.config.max_post_video_seconds
            ),
            upload_length=(data or {}).get("byte_size") or max_bytes,
            creator=profile["profile_id"],
        )
        stamp = _now()
        job_id = _id("upl")
        upload_url = session["upload_url"]
        token = session.get("upload_token") or ""
        self.db.execute(
            "INSERT INTO upload_jobs ("
            "upload_job_id, owner_profile_id, intended_type, provider, provider_uid, "
            "upload_token, upload_url, upload_method, status, expected_kind, byte_size, "
            "duration_seconds, error_code, retry_count, expires_at, idempotency_key, "
            "intended_object_id, created_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job_id, profile["profile_id"], kind, adapter.name,
                session["provider_uid"], token, upload_url,
                session["upload_method"], "authorized", kind, None, None, None, 0,
                session["expiry"], idem, None, stamp, stamp,
            ),
        )
        self._audit("MEDIA_UPLOAD_AUTHORIZED", job_id, "member", user["user_id"],
                    {"kind": kind, "provider": adapter.name})
        return self._safe_upload_contract(
            dict(self._row("upload_jobs", "upload_job_id", job_id)), session,
        )

    def upload_status(self, user, job_id: str) -> dict:
        job = dict(self._row("upload_jobs", "upload_job_id", job_id, "upload not found", "upload_not_found"))
        profile = self.ensure_profile(user)
        if job["owner_profile_id"] != profile["profile_id"] and not self._staff(user):
            raise ForbiddenError("not your upload", "upload_forbidden")
        return {
            "upload_job_id": job["upload_job_id"],
            "status": job["status"],
            "intended_type": job["intended_type"],
            "error_code": job["error_code"],
            "duration_seconds": job["duration_seconds"],
            "intended_object_id": job["intended_object_id"],
        }

    def cancel_upload(self, user, job_id: str) -> dict:
        job = dict(self._row("upload_jobs", "upload_job_id", job_id, "upload not found", "upload_not_found"))
        profile = self.ensure_profile(user)
        if job["owner_profile_id"] != profile["profile_id"]:
            raise ForbiddenError("not your upload", "upload_forbidden")
        if job["status"] == "ready":
            raise ConflictError("ready uploads cannot be cancelled", "upload_ready")
        self.db.execute(
            "UPDATE upload_jobs SET status='expired', updated_at=? WHERE upload_job_id=?",
            (_now(), job_id),
        )
        return {"ok": True, "status": "expired"}

    def retry_upload(self, user, job_id: str) -> dict:
        job = dict(self._row("upload_jobs", "upload_job_id", job_id, "upload not found", "upload_not_found"))
        profile = self.ensure_profile(user)
        if job["owner_profile_id"] != profile["profile_id"]:
            raise ForbiddenError("not your upload", "upload_forbidden")
        if job["status"] not in ("failed", "expired"):
            raise ConflictError("only failed or expired jobs can be retried", "retry_not_allowed")
        self.db.execute(
            "UPDATE upload_jobs SET retry_count=retry_count+1, status='failed', updated_at=? WHERE upload_job_id=?",
            (_now(), job_id),
        )
        return self.create_upload(user, {"kind": job["intended_type"], "retry": True})

    def complete_fake_upload(self, token: str, meta: dict | None = None, user=None) -> dict:
        if user is not None:
            self._require_fake_upload_owner(user, token)
            self.limiter.check(f"fake_complete:{user.get('user_id') or 'unknown'}", 30)
        payload = None
        if hasattr(self.provider, "uploads") and token in getattr(self.provider, "uploads", {}):
            payload = self.provider.complete_upload(token, meta or {})
        elif hasattr(self.photo_storage, "uploads") and token in getattr(self.photo_storage, "uploads", {}):
            payload = self.photo_storage.complete_upload(token, meta or {})
        if payload is None:
            raise ForbiddenError("unknown fake upload token", "unknown_upload")
        return self.apply_webhook(
            {"X-Network-Webhook-Secret": self.cp.config.fake_webhook_secret}, payload,
        )

    def _require_fake_upload_owner(self, user, token: str) -> None:
        job = self.db.query_one("SELECT * FROM upload_jobs WHERE upload_token=?", (token,))
        if not job:
            suffix = f"/api/network/provider/fake/upload/{token}"
            job = self.db.query_one("SELECT * FROM upload_jobs WHERE upload_url=?", (suffix,))
        if not job:
            raise ForbiddenError("unknown fake upload token", "unknown_upload")
        if self._staff(user):
            return
        profile = self.ensure_profile(user)
        if job["owner_profile_id"] != profile["profile_id"]:
            raise ForbiddenError("not your upload", "upload_forbidden")

    def apply_webhook(self, headers: dict, body: dict, raw_body: bytes | None = None) -> dict:
        body = body or {}
        chosen = None
        for adapter in self._webhook_adapters():
            if adapter.verify_webhook(headers or {}, body, raw_body):
                chosen = adapter
                break
        if chosen is None:
            raise AuthError("invalid webhook signature", "bad_webhook")
        event = chosen.normalize_webhook(headers or {}, raw_body, body)
        event_id = (event.get("provider_event_id") or "").strip()
        uid = (event.get("provider_uid") or "").strip()
        status = (event.get("status") or "").strip()
        if not event_id or not uid:
            raise ValidationError("malformed webhook", "bad_webhook_body")
        existing = self.db.query_one(
            "SELECT * FROM provider_webhook_events WHERE provider_event_id=?", (event_id,)
        )
        if existing:
            return {"ok": True, "duplicate": True}
        self.db.execute(
            "INSERT INTO provider_webhook_events VALUES (?,?,?,?,?)",
            (event_id, chosen.name, uid, status, _now()),
        )
        job = self.db.query_one("SELECT * FROM upload_jobs WHERE provider_uid=?", (uid,))
        clip = self.db.query_one("SELECT * FROM clips WHERE derived_media_asset_id IN "
                                 "(SELECT media_asset_id FROM media_assets WHERE provider_uid=?) "
                                 "OR provider_job_id=?", (uid, event.get("job_id")))
        if job and job["status"] == "ready" and status != "ready":
            return {"ok": True, "ignored": "stale"}
        mapped = {
            "ready": "ready", "ok": "ready", "uploaded": "uploaded",
            "processing": "processing", "error": "failed", "failed": "failed",
            "queued": "processing", "authorized": "authorized",
        }.get(status, status or "processing")
        stamp = _now()
        duration = event.get("duration_seconds")
        if job:
            if mapped == "ready":
                self._audit("MEDIA_UPLOAD_COMPLETED", job["upload_job_id"], "system", "media-provider")
                self._audit("MEDIA_PROCESSING_STARTED", job["upload_job_id"], "system", "media-provider")
                asset_id = self._ensure_asset(job, uid, duration, event.get("byte_size"))
                self.db.execute(
                    "UPDATE upload_jobs SET status='ready', duration_seconds=?, byte_size=?, updated_at=? "
                    "WHERE upload_job_id=?",
                    (duration, event.get("byte_size"), stamp, job["upload_job_id"]),
                )
                self._link_ready_job(dict(job), asset_id, duration)
                self._audit("MEDIA_READY", asset_id, "system", "media-provider")
            elif mapped in ("failed", "quarantined", "expired"):
                self.db.execute(
                    "UPDATE upload_jobs SET status=?, error_code=?, updated_at=? WHERE upload_job_id=?",
                    (mapped, event.get("error_code") or mapped, stamp, job["upload_job_id"]),
                )
            else:
                self.db.execute(
                    "UPDATE upload_jobs SET status=?, updated_at=? WHERE upload_job_id=?",
                    (mapped, stamp, job["upload_job_id"]),
                )
        if clip and mapped == "ready":
            asset_id = clip["derived_media_asset_id"] or self._asset_from_uid(
                clip["creator_profile_id"], uid, "clip", duration
            )
            self.db.execute(
                "UPDATE clips SET publication_status=CASE WHEN publication_status='rendering' "
                "THEN 'ready' ELSE publication_status END, derived_media_asset_id=?, updated_at=? "
                "WHERE clip_id=?",
                (asset_id, stamp, clip["clip_id"]),
            )
            self._audit("CLIP_READY", clip["clip_id"], "system", "media-provider")
        return {"ok": True, "status": mapped}

    def _ensure_asset(self, job, uid, duration, byte_size):
        existing = self.db.query_one(
            "SELECT media_asset_id FROM media_assets WHERE provider=? AND provider_uid=?",
            (job["provider"], uid),
        )
        if existing:
            return existing["media_asset_id"]
        asset_id = _id("med")
        self.db.execute(
            "INSERT INTO media_assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, job["owner_profile_id"], job["provider"], uid, job["expected_kind"],
             duration, byte_size, "ready", "", _now(), _now()),
        )
        return asset_id

    def _asset_from_uid(self, owner_profile_id, uid, kind, duration):
        existing = self.db.query_one(
            "SELECT media_asset_id FROM media_assets WHERE provider=? AND provider_uid=?",
            (self.provider.name, uid),
        )
        if existing:
            return existing["media_asset_id"]
        asset_id = _id("med")
        self.db.execute(
            "INSERT INTO media_assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, owner_profile_id, self.provider.name, uid, kind,
             duration, None, "ready", "", _now(), _now()),
        )
        return asset_id

    def _link_ready_job(self, job, asset_id, duration):
        if job["intended_type"] == "game" and job.get("intended_object_id"):
            source = self.db.query_one(
                "SELECT media_asset_id FROM games WHERE game_id=?", (job["intended_object_id"],)
            )
            # Never overwrite an existing source media pointer.
            if source and source["media_asset_id"]:
                self.db.execute(
                    "INSERT OR IGNORE INTO game_media VALUES (?,?,?,?)",
                    (job["intended_object_id"], asset_id, "derived_ready", _now()),
                )
            else:
                self.db.execute(
                    "UPDATE games SET media_asset_id=?, processing_status='ready', duration_seconds=?, "
                    "updated_at=? WHERE game_id=?",
                    (asset_id, duration, _now(), job["intended_object_id"]),
                )
                self.db.execute(
                    "INSERT OR IGNORE INTO game_media VALUES (?,?,?,?)",
                    (job["intended_object_id"], asset_id, "source", _now()),
                )
        if job["intended_type"] in ("photo", "clip") and job.get("intended_object_id"):
            self.db.execute(
                "UPDATE posts SET media_asset_id=?, publication_status='published', published_at=?, "
                "updated_at=? WHERE post_id=? AND publication_status IN ('draft','processing')",
                (asset_id, _now(), _now(), job["intended_object_id"]),
            )

    # -- posts / feed ------------------------------------------------------
    def create_post(self, user, data: dict) -> dict:
        data = data or {}
        profile = self.ensure_profile(user)
        visibility = data.get("visibility") or "public"
        if visibility not in VISIBILITY:
            raise ValidationError("invalid visibility", "bad_visibility")
        sport = (data.get("sport") or "other").lower()
        if sport not in SPORTS:
            raise ValidationError("unsupported sport", "bad_sport")
        caption = _safe_text(data.get("caption") or "", 2000)
        asset_id = data.get("media_asset_id")
        job_id = data.get("upload_job_id")
        clip_id = data.get("clip_id")
        status = "published"
        if job_id:
            job = dict(self._row("upload_jobs", "upload_job_id", job_id, "upload not found", "upload_not_found"))
            if job["owner_profile_id"] != profile["profile_id"]:
                raise ForbiddenError("not your upload", "upload_forbidden")
            if job["status"] == "ready":
                asset = self.db.query_one(
                    "SELECT media_asset_id FROM media_assets WHERE provider=? AND provider_uid=?",
                    (job["provider"], job["provider_uid"]),
                )
                asset_id = asset["media_asset_id"] if asset else asset_id
            else:
                status = "processing"
        if clip_id:
            clip = self.require_clip(user, clip_id)
            if clip["creator_profile_id"] != profile["profile_id"] and not self._staff(user):
                raise ForbiddenError("not your clip", "clip_forbidden")
            if not self._clip_may_publish(user, clip, visibility):
                raise ForbiddenError("clip exceeds source game rights", "rights_exceeded")
        stamp = _now()
        post_id = _id("pst")
        self.db.execute(
            "INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (post_id, profile["profile_id"], asset_id, clip_id, caption, sport, visibility,
             status, 1 if data.get("comments_enabled", True) else 0,
             data.get("event_id"), stamp, stamp if status == "published" else None, stamp),
        )
        if job_id:
            self.db.execute(
                "UPDATE upload_jobs SET intended_object_id=?, updated_at=? WHERE upload_job_id=?",
                (post_id, stamp, job_id),
            )
        if clip_id:
            self.db.execute(
                "UPDATE clips SET post_id=?, publication_status=?, visibility=?, caption=?, "
                "published_at=?, updated_at=? WHERE clip_id=?",
                (post_id, status, visibility, caption, stamp if status == "published" else None, stamp, clip_id),
            )
        tagged_profiles, tagged_teams = self._resolve_tag_inputs(data)
        self._tag("post", post_id, tagged_profiles, tagged_teams)
        result = self._classify(caption, sport)
        self._flag("post", post_id, result)
        if status == "published":
            self._audit("POST_PUBLISHED", post_id, "member", user["user_id"],
                        {"visibility": visibility, "sport": sport})
            self._outbox(post_id, "network.post.published", {
                "post_id": post_id, "author_profile_id": profile["profile_id"], "sport": sport,
            })
        return self.post_view(user, post_id)

    def update_post(self, user, post_id: str, data: dict) -> dict:
        post = dict(self._row("posts", "post_id", post_id, "post not found", "post_not_found"))
        profile = self.ensure_profile(user)
        if post["author_profile_id"] != profile["profile_id"] and not self._staff(user):
            raise ForbiddenError("not your post", "post_forbidden")
        data = data or {}
        visibility = data.get("visibility") or post["visibility"]
        if visibility not in VISIBILITY:
            raise ValidationError("invalid visibility", "bad_visibility")
        caption = _safe_text(data["caption"], 2000) if "caption" in data else post["caption"]
        comments = post["comments_enabled"] if "comments_enabled" not in data else (
            1 if data.get("comments_enabled") else 0
        )
        self.db.execute(
            "UPDATE posts SET caption=?, visibility=?, comments_enabled=?, updated_at=? WHERE post_id=?",
            (caption, visibility, comments, _now(), post_id),
        )
        if visibility != post["visibility"]:
            self._audit("POST_VISIBILITY_CHANGED", post_id, "member", user["user_id"],
                        {"from": post["visibility"], "to": visibility})
        return self.post_view(user, post_id)

    def delete_post(self, user, post_id: str) -> dict:
        post = dict(self._row("posts", "post_id", post_id, "post not found", "post_not_found"))
        profile = self.ensure_profile(user)
        if post["author_profile_id"] != profile["profile_id"] and not self._staff(user):
            raise ForbiddenError("not your post", "post_forbidden")
        self.db.execute(
            "UPDATE posts SET publication_status='removed', updated_at=? WHERE post_id=?",
            (_now(), post_id),
        )
        self._audit("POST_REMOVED", post_id, "member", user["user_id"])
        return {"ok": True, "publication_status": "removed"}

    def post_view(self, viewer, post_id: str) -> dict:
        post = self.require_post(viewer, post_id)
        return self._serialize_post(viewer, post)

    def _serialize_post(self, viewer, post) -> dict:
        author = dict(self._row("profiles", "profile_id", post["author_profile_id"]))
        likes, comments = self._counts("post", post["post_id"])
        reacted = False
        saved = False
        if viewer:
            actor = self.ensure_profile(viewer)
            reacted = bool(self.db.query_one(
                "SELECT 1 FROM reactions WHERE actor_profile_id=? AND subject_type='post' "
                "AND subject_id=? AND kind='like'",
                (actor["profile_id"], post["post_id"]),
            ))
            saved = bool(self.db.query_one(
                "SELECT 1 FROM saves WHERE profile_id=? AND subject_type='post' AND subject_id=?",
                (actor["profile_id"], post["post_id"]),
            ))
        content_state = (
            "restricted" if post["publication_status"] == "restricted"
            else "removed" if post["publication_status"] == "removed"
            else "ok"
        )
        card = {
            "post_id": post["post_id"],
            "type": "game_clip" if post.get("clip_id") else "post",
            "author": self.public_profile(author, viewer),
            "caption": post["caption"],
            "sport": post["sport"],
            "visibility": post["visibility"],
            "publication_status": post["publication_status"],
            "media_asset_id": post["media_asset_id"],
            "clip_id": post["clip_id"],
            "like_count": likes,
            "comment_count": comments,
            "viewer_liked": reacted,
            "viewer_saved": saved,
            "comments_enabled": bool(post["comments_enabled"]),
            "created_at": post["created_at"],
            "published_at": post["published_at"],
            "provenance": None,
            "watch_full_game": None,
            "content_state": content_state,
            "source": None,
            "media": None,
            "engagement": {
                "likes": likes,
                "comments": comments,
                "shares": 0,
                "liked_by_me": reacted,
                "saved_by_me": saved,
            },
        }
        card.update(self._post_tags(post["post_id"]))
        if post["clip_id"]:
            clip = dict(self._row("clips", "clip_id", post["clip_id"]))
            available = self.clip_media_available(viewer, clip)
            card["provenance"] = self.clip_provenance(viewer, clip)
            card["watch_full_game"] = card["provenance"].get("watch_full_game")
            card["derived_media_asset_id"] = clip.get("derived_media_asset_id") if available else None
            card["source_media_asset_id"] = clip.get("source_media_asset_id") if available else None
            card["media_asset_id"] = (card["media_asset_id"] or clip.get("derived_media_asset_id")) if available else None
            card["source"] = {
                "event_id": card["provenance"].get("event_id"),
                "rights_version": card["provenance"].get("rights_version"),
                "start_ms": int((clip.get("start_seconds") or 0) * 1000),
                "end_ms": int((clip.get("end_seconds") or 0) * 1000),
            }
            if available and clip.get("derived_media_asset_id"):
                card["media"] = {
                    "kind": "clip",
                    "clip_id": clip["clip_id"],
                    "poster_url": None,
                    "playback_url": f"/api/network/media/{clip['derived_media_asset_id']}",
                    "duration_seconds": max(0, (clip.get("end_seconds") or 0) - (clip.get("start_seconds") or 0)),
                }
            if not available:
                card["content_state"] = "unavailable"
                card["watch_full_game"] = {
                    "game_id": clip.get("source_game_id"),
                    "authorized": False,
                    "label": "This moment is no longer available.",
                }
        elif post["media_asset_id"]:
            card["provenance"] = {"label": "Member Upload", "source_type": "member_upload"}
            card["media"] = {
                "kind": "photo",
                "playback_url": f"/api/network/media/{post['media_asset_id']}",
            }
        return card

    def feed(self, viewer, mode: str = "for_you", sport: str | None = None,
             cursor: str | None = None, limit: int = 20) -> dict:
        requested_mode = mode or "for_you"
        if requested_mode in ("zone", "in_your_zone"):
            mode = "local"
        if mode not in ("for_you", "following", "local"):
            raise ValidationError("mode must be for_you, following, local, or zone", "bad_feed_mode")
        if sport and sport not in SPORTS:
            raise ValidationError("unsupported sport", "bad_sport")
        limit = max(1, min(int(limit or 20), 50))
        decoded = decode_cursor(cursor)
        rows = self.db.query(
            "SELECT * FROM posts WHERE publication_status='published' ORDER BY published_at DESC, post_id DESC"
        )
        actor = self.ensure_profile(viewer) if viewer else None
        following = set()
        friend_ids = set()
        team_ids = set()
        live_event_ids = set()
        if actor:
            following = {
                r["followed_profile_id"]
                for r in self.db.query(
                    "SELECT followed_profile_id FROM follows WHERE follower_profile_id=?",
                    (actor["profile_id"],),
                )
            }
            friend_ids = self._friend_ids(actor["profile_id"])
            team_ids = self._followed_team_ids(actor["profile_id"])
            live_event_ids = {
                e["event_id"] for e in self.portal.live(viewer) if e.get("status") == "live"
            }
        candidates = []
        seen = set()
        for row in rows:
            post = dict(row)
            if post["post_id"] in seen:
                continue
            if sport and post["sport"] != sport:
                continue
            if mode == "following":
                if not actor or post["author_profile_id"] not in following:
                    continue
            if mode == "local":
                if not actor:
                    continue
                author = self.db.query_one(
                    "SELECT market FROM profiles WHERE profile_id=?", (post["author_profile_id"],)
                )
                if not author or author["market"] != actor["market"]:
                    continue
            if not self.can_see_post(viewer, post):
                continue
            seen.add(post["post_id"])
            score = self._feed_score(viewer, actor, post, following, friend_ids, team_ids, live_event_ids)
            candidates.append((score, post))
        if mode == "for_you":
            candidates.sort(key=lambda item: (-item[0], -(item[1].get("published_at") or 0), item[1]["post_id"]))
        ranked = []
        skip = bool(decoded)
        for score, post in candidates:
            if skip:
                if post["post_id"] == decoded[1]:
                    skip = False
                continue
            ranked.append(self._serialize_post(viewer, post))
            if len(ranked) >= limit:
                break
        next_cursor = None
        if ranked and len(ranked) == limit:
            last = ranked[-1]
            next_cursor = encode_cursor(last["published_at"], last["post_id"])
        return {
            "mode": requested_mode,
            "sport": sport,
            "ranking": "sports-relevance" if mode == "for_you" else "published_at DESC, post_id DESC",
            "items": ranked,
            "cursor": next_cursor,
            "next_cursor": next_cursor,
        }

    def profile_collection(self, viewer, handle: str, tab: str) -> dict:
        target = dict(self._row("profiles", "handle", handle.lower(), "profile not found", "profile_not_found"))
        public = self.get_profile_by_handle(handle, viewer)
        items = []
        if tab == "posts":
            rows = self.db.query(
                "SELECT * FROM posts WHERE author_profile_id=? ORDER BY created_at DESC",
                (target["profile_id"],),
            )
            items = [self._serialize_post(viewer, dict(r)) for r in rows if self.can_see_post(viewer, dict(r))]
        elif tab == "clips":
            rows = self.db.query(
                "SELECT * FROM clips WHERE creator_profile_id=? ORDER BY created_at DESC",
                (target["profile_id"],),
            )
            for r in rows:
                clip = dict(r)
                if self.can_see_clip(viewer, clip):
                    items.append(self.clip_view(viewer, clip["clip_id"]))
        elif tab == "games":
            rows = self.db.query(
                "SELECT * FROM games WHERE uploader_profile_id=? ORDER BY created_at DESC",
                (target["profile_id"],),
            )
            for r in rows:
                game = dict(r)
                if self.can_see_game(viewer, game):
                    items.append(self.game_view(viewer, game["game_id"]))
        elif tab == "saved":
            if not viewer or self.ensure_profile(viewer)["profile_id"] != target["profile_id"]:
                raise ForbiddenError("saved is private", "saved_private")
            rows = self.db.query(
                "SELECT * FROM saves WHERE profile_id=? ORDER BY created_at DESC",
                (target["profile_id"],),
            )
            for r in rows:
                if r["subject_type"] == "post":
                    try:
                        items.append(self.post_view(viewer, r["subject_id"]))
                    except (ForbiddenError, NotFoundError):
                        continue
        else:
            raise ValidationError("tab must be posts, clips, games, or saved", "bad_tab")
        return {"profile": public, "tab": tab, "items": items}

    # -- games / studio ----------------------------------------------------
    def _next_game_number(self) -> str:
        year = time.gmtime().tm_year
        row = self.db.query_one("SELECT COUNT(*) AS c FROM games")
        return f"G-{year}-{(row['c'] if row else 0) + 1:04d}"

    def submit_game(self, user, data: dict) -> dict:
        data = data or {}
        if not data.get("rights_attestation"):
            raise ValidationError("uploader must attest they have the right to upload", "attestation_required")
        profile = self.ensure_profile(user)
        sport = (data.get("sport") or "other").lower()
        if sport not in SPORTS:
            raise ValidationError("unsupported sport", "bad_sport")
        visibility = data.get("visibility") or "private"
        if visibility not in VISIBILITY:
            raise ValidationError("invalid visibility", "bad_visibility")
        if visibility == "public":
            # Public full games require verification; never auto-broadcast.
            visibility = "private"
        level = (data.get("level") or "other").replace(" ", "_").replace("/", "_").lower()
        if level not in LEVELS:
            level = "other"
        source_type = data.get("source_type") or "member_upload"
        if source_type not in SOURCE_TYPES:
            raise ValidationError("unsupported source type", "bad_source_type")
        event_id = data.get("event_id") or None
        rights_version = None
        if event_id:
            event = self.cp.get_event_row(event_id)
            rights = self.cp.current_rights(event_id)
            if rights:
                rights_version = rights["version"]
            self._audit("GAME_ATTACHED_TO_EVENT", event_id, "member", user["user_id"],
                        {"event_id": event_id, "rights_version": rights_version})
        stamp = _now()
        game_id = _id("gme")
        number = data.get("game_number") or self._next_game_number()
        self.db.execute(
            "INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                game_id, number, event_id, sport,
                data.get("home_team_id"), data.get("away_team_id"),
                _safe_text(data.get("home_team_name") or "", 80),
                _safe_text(data.get("away_team_name") or "", 80),
                data.get("game_date") or stamp, data.get("timezone") or "America/Chicago",
                _safe_text(data.get("season") or "", 20), level,
                _safe_text(data.get("venue") or "", 120), profile["profile_id"],
                source_type, None, "uploading", visibility, "pending", rights_version,
                data.get("archive_id"), None, 1, stamp, stamp,
            ),
        )
        upload = self.create_upload(user, {
            "kind": "game", "idempotency_key": data.get("idempotency_key") or game_id,
        })
        self.db.execute(
            "UPDATE upload_jobs SET intended_object_id=? WHERE upload_job_id=?",
            (game_id, upload["upload_job_id"]),
        )
        self._audit("GAME_SUBMITTED", game_id, "member", user["user_id"],
                    {"game_number": number, "visibility": visibility})
        self._outbox(game_id, "network.game.submitted", {"game_id": game_id, "game_number": number})
        view = self.game_view(user, game_id)
        view["upload"] = upload
        return view

    def attach_game_event(self, user, game_id: str, event_id: str) -> dict:
        game = dict(self._row("games", "game_id", game_id, "game not found", "game_not_found"))
        profile = self.ensure_profile(user)
        if game["uploader_profile_id"] != profile["profile_id"] and not self._staff(user):
            raise ForbiddenError("not your game", "game_forbidden")
        self.cp.get_event_row(event_id)
        rights = self.cp.current_rights(event_id)
        version = rights["version"] if rights else None
        self.db.execute(
            "UPDATE games SET event_id=?, rights_version=?, updated_at=? WHERE game_id=?",
            (event_id, version, _now(), game_id),
        )
        self._audit("GAME_ATTACHED_TO_EVENT", game_id, "member", user["user_id"],
                    {"event_id": event_id, "rights_version": version})
        return self.game_view(user, game_id)

    def game_view(self, viewer, game_id: str) -> dict:
        game = self.require_game(viewer, game_id)
        uploader = dict(self._row("profiles", "profile_id", game["uploader_profile_id"]))
        source = None
        if game["media_asset_id"]:
            source = dict(self._row("media_assets", "media_asset_id", game["media_asset_id"]))
        rights_ok = True
        if game.get("event_id") and viewer:
            decision = self._event_access(viewer, game["event_id"])
            rights_ok = bool(decision and decision["allow"])
        return {
            "game_id": game["game_id"],
            "game_number": game["game_number"],
            "event_id": game["event_id"],
            "sport": game["sport"],
            "home_team_name": game["home_team_name"],
            "away_team_name": game["away_team_name"],
            "game_date": game["game_date"],
            "timezone": game["timezone"],
            "season": game["season"],
            "level": game["level"],
            "venue": game["venue"],
            "uploader": self.public_profile(uploader, viewer),
            "source_type": game["source_type"],
            "processing_status": game["processing_status"],
            "visibility": game["visibility"],
            "verification_status": game["verification_status"] if self._staff(viewer) or (
                viewer and self.ensure_profile(viewer)["profile_id"] == game["uploader_profile_id"]
            ) else None,
            "duration_seconds": game["duration_seconds"],
            "rights_version": game["rights_version"],
            "source_media_asset_id": game["media_asset_id"],
            "source_provider_uid": source["provider_uid"] if source else None,
            "can_create_clip": game["processing_status"] == "ready" and rights_ok,
            "can_watch": rights_ok and game["processing_status"] == "ready",
        }

    def game_playback(self, user, game_id: str) -> dict:
        game = self.require_game(user, game_id)
        if game["processing_status"] != "ready":
            raise ForbiddenError("game is not ready", "game_not_ready")
        if game.get("event_id"):
            decision = self._event_access(user, game["event_id"])
            if not decision or not decision["allow"]:
                self._audit("PLAYBACK_DENIED", game_id, "member", user["user_id"],
                            {"reason": (decision or {}).get("code")})
                raise ForbiddenError("this game is not currently available with your access", "playback_denied")
            lease = self.cp.request_playback(game["event_id"], user)
            self._audit("PLAYBACK_LEASE_ISSUED", game_id, "member", user["user_id"],
                        {"event_id": game["event_id"]}, rights_version=lease["rights_version"])
            return {
                "allow": True,
                "media_url": f"/api/network/media/{game['media_asset_id']}",
                "event_media_url": lease["media_url"],
                "lease_id": lease["lease_id"],
                "lease_token": lease["lease_token"],
                "event_id": game["event_id"],
                "rights_version": lease["rights_version"],
            }
        self._audit("PLAYBACK_LEASE_ISSUED", game_id, "member", user["user_id"])
        return {
            "allow": True,
            "media_url": f"/api/network/media/{game['media_asset_id']}",
            "lease_id": _id("nls"),
            "rights_version": game["rights_version"],
        }

    def validate_clip_bounds(self, start, end, duration, max_len=None) -> tuple[float, float]:
        try:
            start = float(start)
            end = float(end)
        except (TypeError, ValueError):
            raise ValidationError("start and end must be numbers", "bad_clip_bounds")
        duration = float(duration or 0)
        max_len = float(max_len or self.cp.config.max_game_clip_seconds)
        min_len = float(getattr(self.cp.config, "min_game_clip_seconds", 5) or 0)
        if not (0 <= start < end <= duration):
            raise ValidationError("clip must satisfy 0 <= start < end <= source duration", "bad_clip_bounds")
        if end - start > max_len:
            raise ValidationError(f"clip cannot exceed {int(max_len)} seconds", "clip_too_long")
        if min_len and end - start < min_len:
            raise ValidationError(f"clip must be at least {int(min_len)} seconds", "clip_too_short")
        return start, end

    def create_clip_definition(self, user, data: dict) -> dict:
        data = data or {}
        game = self.require_game(user, data.get("source_game_id") or "")
        if game["processing_status"] != "ready" or not game["duration_seconds"]:
            raise ConflictError("game is not ready to clip", "game_not_ready")
        snapshot = {
            "media_asset_id": game["media_asset_id"],
            "duration_seconds": game["duration_seconds"],
            "event_id": game["event_id"],
            "rights_version": game["rights_version"],
        }
        start, end = self.validate_clip_bounds(
            data.get("start_seconds"), data.get("end_seconds"), game["duration_seconds"],
        )
        profile = self.ensure_profile(user)
        source = dict(self._row("media_assets", "media_asset_id", game["media_asset_id"]))
        stamp = _now()
        clip_id = _id("clp")
        self.db.execute(
            "INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                clip_id, None, profile["profile_id"], "game_clip", game["media_asset_id"],
                game["game_id"], start, end, None, None,
                _safe_text(data.get("caption") or "", 2000), game["sport"],
                game["rights_version"], "pending", "draft",
                data.get("visibility") or "private", stamp, None, stamp,
            ),
        )
        self._audit("CLIP_DEFINITION_CREATED", clip_id, "member", user["user_id"], {
            "source_game_id": game["game_id"],
            "source_provider_uid": source["provider_uid"],
            "start_seconds": start, "end_seconds": end,
            "rights_version": game["rights_version"],
        }, rights_version=game["rights_version"])
        # Source game must remain unchanged.
        after = dict(self._row("games", "game_id", game["game_id"]))
        if after["media_asset_id"] != snapshot["media_asset_id"] or after["duration_seconds"] != snapshot["duration_seconds"]:
            raise ConflictError("source game mutated", "source_mutated")
        return self.clip_view(user, clip_id)

    def render_clip(self, user, clip_id: str) -> dict:
        self.limiter.check(f"render:{user['user_id']}", 10)
        clip = dict(self._row("clips", "clip_id", clip_id, "clip not found", "clip_not_found"))
        profile = self.ensure_profile(user)
        if clip["creator_profile_id"] != profile["profile_id"] and not self._staff(user):
            raise ForbiddenError("not your clip", "clip_forbidden")
        if clip["provider_job_id"] and clip["publication_status"] in ("rendering", "ready"):
            return self.clip_view(user, clip_id)
        if clip.get("source_game_id"):
            game = dict(self._row("games", "game_id", clip["source_game_id"]))
            if game.get("event_id"):
                decision = self._event_access(user, game["event_id"])
                if decision and not decision["allow"]:
                    raise ForbiddenError("source rights no longer allow derived publication", "rights_revoked")
            source = dict(self._row("media_assets", "media_asset_id", clip["source_media_asset_id"]))
            source_uid = source["provider_uid"]
        else:
            source = dict(self._row("media_assets", "media_asset_id", clip["source_media_asset_id"]))
            source_uid = source["provider_uid"]
        job = self.provider.create_clip(source_uid, clip["start_seconds"], clip["end_seconds"])
        derived_id = self._asset_from_uid(profile["profile_id"], job["provider_uid"], "clip",
                                         (clip["end_seconds"] - clip["start_seconds"]))
        self.db.execute(
            "UPDATE media_assets SET status='processing', updated_at=? WHERE media_asset_id=?",
            (_now(), derived_id),
        )
        self.db.execute(
            "UPDATE clips SET provider_job_id=?, derived_media_asset_id=?, publication_status='rendering', "
            "updated_at=? WHERE clip_id=?",
            (job["job_id"], derived_id, _now(), clip_id),
        )
        self._audit("CLIP_RENDER_STARTED", clip_id, "member", user["user_id"],
                    {"job_id": job["job_id"]})
        if hasattr(self.provider, "finalize_clip"):
            payload = self.provider.finalize_clip(job["job_id"])
            self.apply_webhook({"X-Network-Webhook-Secret": self.cp.config.fake_webhook_secret}, payload)
        return self.clip_view(user, clip_id)

    def _clip_may_publish(self, user, clip, visibility) -> bool:
        if not clip.get("source_game_id"):
            return True
        game = dict(self._row("games", "game_id", clip["source_game_id"]))
        if game["verification_status"] in ("rejected", "rights_restricted"):
            return False
        if visibility == "public" and game["visibility"] != "public":
            return False
        if game.get("event_id"):
            decision = self._event_access(user, game["event_id"])
            if decision and not decision["allow"]:
                return False
            rights = self.cp.current_rights(game["event_id"])
            if not rights or rights["revoked"]:
                return False
            if clip.get("source_rights_version") is not None and rights["version"] != clip["source_rights_version"]:
                return False
        return True

    def publish_clip(self, user, clip_id: str, data: dict) -> dict:
        clip = dict(self._row("clips", "clip_id", clip_id, "clip not found", "clip_not_found"))
        profile = self.ensure_profile(user)
        if clip["creator_profile_id"] != profile["profile_id"] and not self._staff(user):
            raise ForbiddenError("not your clip", "clip_forbidden")
        if clip["publication_status"] not in ("ready", "published"):
            raise ConflictError("clip is not ready to publish", "clip_not_ready")
        data = data or {}
        visibility = data.get("visibility") or clip["visibility"]
        if visibility not in VISIBILITY:
            raise ValidationError("invalid visibility", "bad_visibility")
        if not self._clip_may_publish(user, clip, visibility):
            raise ForbiddenError("clip exceeds source game rights", "rights_exceeded")
        caption = _safe_text(data["caption"], 2000) if "caption" in data else clip["caption"]
        if clip.get("post_id"):
            self.db.execute(
                "UPDATE posts SET caption=?, visibility=?, publication_status='published', "
                "published_at=COALESCE(published_at, ?), updated_at=? WHERE post_id=?",
                (caption, visibility, _now(), _now(), clip["post_id"]),
            )
            self.db.execute(
                "UPDATE clips SET caption=?, visibility=?, publication_status='published', "
                "published_at=COALESCE(published_at, ?), updated_at=? WHERE clip_id=?",
                (caption, visibility, _now(), _now(), clip_id),
            )
            result = self.post_view(user, clip["post_id"])
        else:
            result = self.create_post(user, {
                "clip_id": clip_id, "caption": caption, "sport": data.get("sport") or clip["sport"],
                "visibility": visibility, "tagged_profile_ids": data.get("tagged_profile_ids"),
                "tagged_handles": data.get("tagged_handles"),
                "tagged_team_ids": data.get("tagged_team_ids"),
            })
        event_id = None
        if clip.get("source_game_id"):
            game = self.db.query_one("SELECT event_id FROM games WHERE game_id=?", (clip["source_game_id"],))
            event_id = game["event_id"] if game else None
        self._moten_handoff("clip-published", clip_id, {
            "schema": "three-zone.moten.clip-published.v1",
            "source_system": "three-zone-mvp",
            "handoff_type": "clip-published",
            "event_type": "threezone.clip.published",
            "object_id": clip_id,
            "object_version": 1,
            "event_id": event_id,
            "source_rights_version": clip.get("source_rights_version"),
            "creator_member_id": user["user_id"],
            "start_ms": int((clip.get("start_seconds") or 0) * 1000),
            "end_ms": int((clip.get("end_seconds") or 0) * 1000),
            "destination": "huddle",
            "publication_decision": "allowed",
        })
        return result

    def clip_view(self, viewer, clip_id: str) -> dict:
        clip = self.require_clip(viewer, clip_id)
        creator = dict(self._row("profiles", "profile_id", clip["creator_profile_id"]))
        return {
            "clip_id": clip["clip_id"],
            "post_id": clip["post_id"],
            "creator": self.public_profile(creator, viewer),
            "source_type": clip["source_type"],
            "source_game_id": clip["source_game_id"],
            "source_media_asset_id": clip["source_media_asset_id"],
            "start_seconds": clip["start_seconds"],
            "end_seconds": clip["end_seconds"],
            "derived_media_asset_id": clip["derived_media_asset_id"],
            "provider_job_id": clip["provider_job_id"],
            "caption": clip["caption"],
            "sport": clip["sport"],
            "publication_status": clip["publication_status"],
            "visibility": clip["visibility"],
            "provenance": self.clip_provenance(viewer, clip),
        }

    def clip_provenance(self, viewer, clip) -> dict:
        if clip["source_type"] == "game_clip" and clip.get("source_game_id"):
            game = dict(self._row("games", "game_id", clip["source_game_id"]))
            source = None
            if game.get("media_asset_id"):
                source = dict(self._row("media_assets", "media_asset_id", game["media_asset_id"]))
            derived = None
            if clip.get("derived_media_asset_id"):
                derived = dict(self._row("media_assets", "media_asset_id", clip["derived_media_asset_id"]))
            authorized = self.can_see_game(viewer, game) if viewer or game["visibility"] == "public" else False
            watch = None
            if authorized:
                watch = {"game_id": game["game_id"], "authorized": True, "label": "Watch Full Game"}
            elif viewer:
                watch = {"game_id": game["game_id"], "authorized": False, "label": "Full game unavailable"}
            return {
                "label": "Three-Zone Game Clip",
                "source_type": "game_clip",
                "clip_id": clip["clip_id"],
                "derived_provider_uid": derived["provider_uid"] if derived else None,
                "source_game_id": game["game_id"],
                "source_provider_uid": source["provider_uid"] if source else None,
                "event_id": game.get("event_id"),
                "rights_version": clip.get("source_rights_version"),
                "watch_full_game": watch,
            }
        return {"label": "Member Upload", "source_type": "member_upload", "watch_full_game": None}

    def create_member_clip(self, user, data: dict) -> dict:
        """Direct member-upload clip (not derived from a game)."""
        data = data or {}
        profile = self.ensure_profile(user)
        asset_id = data.get("source_media_asset_id") or data.get("media_asset_id")
        asset = dict(self._row("media_assets", "media_asset_id", asset_id, "media not found", "media_not_found"))
        stamp = _now()
        clip_id = _id("clp")
        self.db.execute(
            "INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                clip_id, None, profile["profile_id"], "member_upload", asset["media_asset_id"],
                None, None, None, None, asset["media_asset_id"],
                _safe_text(data.get("caption") or "", 2000),
                (data.get("sport") or "other").lower(), None, "allowed",
                "ready", data.get("visibility") or "public", stamp, None, stamp,
            ),
        )
        return self.clip_view(user, clip_id)

    # -- social ------------------------------------------------------------
    def react(self, user, subject_type: str, subject_id: str, kind: str = "like") -> dict:
        if kind != "like":
            raise ValidationError("V1 reactions are likes only", "bad_reaction")
        if subject_type not in ("post", "clip", "game"):
            raise ValidationError("unsupported subject", "bad_subject")
        self._require_subject(user, subject_type, subject_id)
        actor = self.ensure_profile(user)
        self.db.execute(
            "INSERT OR IGNORE INTO reactions VALUES (?,?,?,?,?,?)",
            (_id("rct"), actor["profile_id"], subject_type, subject_id, kind, _now()),
        )
        self._audit("LIKE_CREATED", subject_id, "member", user["user_id"],
                    {"subject_type": subject_type, "kind": kind})
        self._outbox(subject_id, "network.reaction", {
            "actor": actor["profile_id"], "subject_type": subject_type, "subject_id": subject_id, "kind": kind,
        })
        owner = self._subject_owner(subject_type, subject_id)
        self._notify(owner, "like", actor["profile_id"], subject_type, subject_id)
        likes, _ = self._counts(subject_type, subject_id)
        return {"ok": True, "liked": True, "like_count": likes}

    def unreact(self, user, subject_type: str, subject_id: str, kind: str = "like") -> dict:
        actor = self.ensure_profile(user)
        self.db.execute(
            "DELETE FROM reactions WHERE actor_profile_id=? AND subject_type=? AND subject_id=? AND kind=?",
            (actor["profile_id"], subject_type, subject_id, kind),
        )
        likes, _ = self._counts(subject_type, subject_id)
        return {"ok": True, "liked": False, "like_count": likes}

    def add_comment(self, user, subject_type: str, subject_id: str, body: str,
                    parent_comment_id: str | None = None) -> dict:
        self.limiter.check(f"comment:{user['user_id']}", 30)
        post = self._require_subject(user, subject_type, subject_id)
        if subject_type == "post" and not post.get("comments_enabled", 1):
            raise ForbiddenError("comments are disabled", "comments_disabled")
        actor = self.ensure_profile(user)
        text = _safe_text(body, 500)
        if not text:
            raise ValidationError("comment cannot be empty", "empty_comment")
        parent_id = parent_comment_id or None
        if parent_id:
            parent = dict(self._row("comments", "comment_id", parent_id, "comment not found", "comment_not_found"))
            if parent["subject_type"] != subject_type or parent["subject_id"] != subject_id:
                raise ValidationError("parent comment does not belong to this post", "bad_parent")
        comment_id = _id("cmt")
        self.db.execute(
            "INSERT INTO comments(comment_id,subject_type,subject_id,author_profile_id,body,created_at,deleted_at,parent_comment_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (comment_id, subject_type, subject_id, actor["profile_id"], text, _now(), None, parent_id),
        )
        self._audit("COMMENT_CREATED", comment_id, "member", user["user_id"],
                    {"subject_type": subject_type, "subject_id": subject_id})
        self._outbox(subject_id, "network.comment", {
            "comment_id": comment_id, "subject_type": subject_type, "subject_id": subject_id,
        })
        self._notify(self._subject_owner(subject_type, subject_id), "comment",
                     actor["profile_id"], subject_type, subject_id)
        return self.comment_view(comment_id)

    def list_comments(self, viewer, subject_type: str, subject_id: str) -> dict:
        self._require_subject(viewer, subject_type, subject_id)
        rows = self.db.query(
            "SELECT * FROM comments WHERE subject_type=? AND subject_id=? AND deleted_at IS NULL "
            "ORDER BY created_at ASC",
            (subject_type, subject_id),
        )
        return {"comments": [self.comment_view(r["comment_id"]) for r in rows]}

    def delete_comment(self, user, comment_id: str) -> dict:
        row = dict(self._row("comments", "comment_id", comment_id, "comment not found", "comment_not_found"))
        actor = self.ensure_profile(user)
        owner = self._subject_owner(row["subject_type"], row["subject_id"])
        if row["author_profile_id"] != actor["profile_id"] and owner != actor["profile_id"] and not self._staff(user):
            raise ForbiddenError("cannot delete this comment", "comment_forbidden")
        self.db.execute("UPDATE comments SET deleted_at=? WHERE comment_id=?", (_now(), comment_id))
        return {"ok": True}

    def comment_view(self, comment_id: str) -> dict:
        row = dict(self._row("comments", "comment_id", comment_id, "comment not found", "comment_not_found"))
        author = dict(self._row("profiles", "profile_id", row["author_profile_id"]))
        return {
            "comment_id": row["comment_id"],
            "author": self.public_profile(author),
            "body": row["body"],
            "created_at": row["created_at"],
            "parent_comment_id": row["parent_comment_id"] if "parent_comment_id" in row.keys() else None,
        }

    def save_item(self, user, subject_type: str, subject_id: str) -> dict:
        self._require_subject(user, subject_type, subject_id)
        actor = self.ensure_profile(user)
        self.db.execute(
            "INSERT OR IGNORE INTO saves VALUES (?,?,?,?)",
            (actor["profile_id"], subject_type, subject_id, _now()),
        )
        return {"ok": True, "saved": True}

    def unsave_item(self, user, subject_type: str, subject_id: str) -> dict:
        actor = self.ensure_profile(user)
        self.db.execute(
            "DELETE FROM saves WHERE profile_id=? AND subject_type=? AND subject_id=?",
            (actor["profile_id"], subject_type, subject_id),
        )
        return {"ok": True, "saved": False}

    def send_media(self, user, data: dict) -> dict:
        self.limiter.check(f"send:{user['user_id']}", 20)
        data = data or {}
        subject_type = data.get("subject_type")
        subject_id = data.get("subject_id")
        self._require_subject(user, subject_type, subject_id)
        actor = self.ensure_profile(user)
        handle = (data.get("recipient_handle") or "").lower()
        recipient = dict(self._row("profiles", "handle", handle, "recipient not found", "recipient_not_found"))
        idem = (data.get("idempotency_key") or "").strip() or None
        if idem:
            existing = self.db.query_one("SELECT * FROM media_shares WHERE idempotency_key=?", (idem,))
            if existing:
                return {"ok": True, "share_id": existing["share_id"], "duplicate": True}
        share_id = _id("shr")
        self.db.execute(
            "INSERT INTO media_shares VALUES (?,?,?,?,?,?,?,?,?)",
            (share_id, actor["profile_id"], recipient["profile_id"], subject_type, subject_id,
             _safe_text(data.get("message") or "", 280), None, idem, _now()),
        )
        self._audit("MEDIA_SHARED", share_id, "member", user["user_id"],
                    {"subject_type": subject_type, "subject_id": subject_id})
        self._outbox(share_id, "network.share", {
            "share_id": share_id, "recipient": recipient["profile_id"],
        })
        self._notify(recipient["profile_id"], "send", actor["profile_id"], subject_type, subject_id)
        return {"ok": True, "share_id": share_id}

    def inbox(self, user) -> dict:
        actor = self.ensure_profile(user)
        rows = self.db.query(
            "SELECT * FROM media_shares WHERE recipient_profile_id=? ORDER BY created_at DESC",
            (actor["profile_id"],),
        )
        items = []
        for r in rows:
            sender = dict(self._row("profiles", "profile_id", r["sender_profile_id"]))
            items.append({
                "share_id": r["share_id"],
                "sender": self.public_profile(sender, user),
                "subject_type": r["subject_type"],
                "subject_id": r["subject_id"],
                "message": r["message"],
                "read_at": r["read_at"],
                "created_at": r["created_at"],
            })
        return {"items": items}

    def mark_share_read(self, user, share_id: str) -> dict:
        row = dict(self._row("media_shares", "share_id", share_id, "share not found", "share_not_found"))
        actor = self.ensure_profile(user)
        if row["recipient_profile_id"] != actor["profile_id"]:
            raise ForbiddenError("not your inbox item", "inbox_forbidden")
        self.db.execute("UPDATE media_shares SET read_at=? WHERE share_id=?", (_now(), share_id))
        return {"ok": True}

    def report(self, user, data: dict) -> dict:
        self.limiter.check(f"report:{user['user_id']}", 10)
        data = data or {}
        subject_type = data.get("subject_type")
        subject_id = data.get("subject_id")
        self._require_subject(user, subject_type, subject_id)
        actor = self.ensure_profile(user)
        reason = _safe_text(data.get("reason") or "unspecified", 280)
        report_id = _id("rep")
        self.db.execute(
            "INSERT INTO content_reports VALUES (?,?,?,?,?,?)",
            (report_id, subject_type, subject_id, actor["profile_id"], reason, _now()),
        )
        self._flag(subject_type, subject_id, "needs_review", source="member_report",
                   reporter=actor["profile_id"], reason=reason)
        self._audit("CONTENT_REPORTED", report_id, "member", user["user_id"],
                    {"subject_type": subject_type, "subject_id": subject_id})
        return {"ok": True, "report_id": report_id}

    def _require_subject(self, viewer, subject_type, subject_id):
        if subject_type == "post":
            return self.require_post(viewer, subject_id)
        if subject_type == "game":
            return self.require_game(viewer, subject_id)
        if subject_type == "clip":
            return self.require_clip(viewer, subject_id)
        raise ValidationError("unsupported subject", "bad_subject")

    def _subject_owner(self, subject_type, subject_id):
        if subject_type == "post":
            row = self.db.query_one("SELECT author_profile_id AS p FROM posts WHERE post_id=?", (subject_id,))
        elif subject_type == "game":
            row = self.db.query_one("SELECT uploader_profile_id AS p FROM games WHERE game_id=?", (subject_id,))
        elif subject_type == "clip":
            row = self.db.query_one("SELECT creator_profile_id AS p FROM clips WHERE clip_id=?", (subject_id,))
        else:
            return None
        return row["p"] if row else None

    # -- moderation / worker / owner --------------------------------------
    def review_queue(self, operator) -> dict:
        self.cp.require_operator(operator)
        games = [dict(r) for r in self.db.query(
            "SELECT game_id, game_number, processing_status, verification_status, visibility, "
            "uploader_profile_id, event_id, created_at FROM games "
            "WHERE verification_status='pending' OR processing_status IN ('failed','quarantined') "
            "ORDER BY created_at DESC"
        )]
        uploads = [dict(r) for r in self.db.query(
            "SELECT upload_job_id, intended_type, status, error_code, owner_profile_id, created_at "
            "FROM upload_jobs WHERE status IN ('failed','quarantined','processing','authorized') "
            "ORDER BY created_at DESC"
        )]
        cases = [dict(r) for r in self.db.query(
            "SELECT * FROM moderation_cases WHERE policy_decision IS NULL ORDER BY created_at DESC"
        )]
        reports = [dict(r) for r in self.db.query(
            "SELECT * FROM content_reports ORDER BY created_at DESC LIMIT 100"
        )]
        return {"games": games, "uploads": uploads, "cases": cases, "reports": reports}

    def decide_game(self, operator, game_id: str, action: str, reason: str = "") -> dict:
        self.cp.require_operator(operator)
        game = dict(self._row("games", "game_id", game_id, "game not found", "game_not_found"))
        mapping = {
            "verify": ("verified", None),
            "reject": ("rejected", None),
            "restrict": ("rights_restricted", "restricted"),
            "restore": ("verified", None),
        }
        if action not in mapping:
            raise ValidationError("action must be verify, reject, restrict, or restore", "bad_action")
        verification, extra = mapping[action]
        if extra == "restricted":
            self.db.execute(
                "UPDATE games SET verification_status=?, visibility='private', updated_at=? WHERE game_id=?",
                (verification, _now(), game_id),
            )
            self.db.execute(
                "UPDATE clips SET publication_status='restricted', updated_at=? WHERE source_game_id=?",
                (_now(), game_id),
            )
            self.db.execute(
                "UPDATE posts SET publication_status='restricted', updated_at=? WHERE clip_id IN "
                "(SELECT clip_id FROM clips WHERE source_game_id=?)",
                (_now(), game_id),
            )
        else:
            self.db.execute(
                "UPDATE games SET verification_status=?, updated_at=? WHERE game_id=?",
                (verification, _now(), game_id),
            )
            if action == "restore":
                self.db.execute(
                    "UPDATE clips SET publication_status=CASE WHEN publication_status='restricted' "
                    "THEN 'published' ELSE publication_status END, updated_at=? WHERE source_game_id=?",
                    (_now(), game_id),
                )
                self.db.execute(
                    "UPDATE posts SET publication_status=CASE WHEN publication_status='restricted' "
                    "THEN 'published' ELSE publication_status END, updated_at=? WHERE clip_id IN "
                    "(SELECT clip_id FROM clips WHERE source_game_id=?)",
                    (_now(), game_id),
                )
        self._audit("GAME_VERIFICATION_CHANGED", game_id, "operator", operator["user_id"],
                    {"action": action, "reason": reason, "from": game["verification_status"],
                     "to": verification})
        return self.game_view(operator, game_id)

    def decide_moderation(self, operator, case_id: str, action: str, reason: str = "") -> dict:
        self.cp.require_operator(operator)
        case = dict(self._row("moderation_cases", "case_id", case_id, "case not found", "case_not_found"))
        if action not in ("restrict", "remove", "quarantine", "restore", "warn"):
            raise ValidationError("unsupported moderation action", "bad_moderation_action")
        subject_type, subject_id = case["subject_type"], case["subject_id"]
        status = {
            "restrict": "restricted", "remove": "removed", "quarantine": "restricted",
            "restore": "published", "warn": None,
        }[action]
        if status and subject_type == "post":
            self.db.execute(
                "UPDATE posts SET publication_status=?, updated_at=? WHERE post_id=?",
                (status, _now(), subject_id),
            )
        if status and subject_type == "clip":
            self.db.execute(
                "UPDATE clips SET publication_status=?, updated_at=? WHERE clip_id=?",
                (status, _now(), subject_id),
            )
        if subject_type == "game":
            if action == "quarantine":
                self.db.execute(
                    "UPDATE games SET processing_status='quarantined', updated_at=? WHERE game_id=?",
                    (_now(), subject_id),
                )
            elif action == "restore":
                self.db.execute(
                    "UPDATE games SET processing_status='ready', updated_at=? WHERE game_id=?",
                    (_now(), subject_id),
                )
            elif status:
                self.db.execute(
                    "UPDATE games SET visibility='private', updated_at=? WHERE game_id=?",
                    (_now(), subject_id),
                )
        self.db.execute(
            "UPDATE moderation_cases SET policy_decision=?, reviewer_id=?, reason=?, action=?, "
            "decided_at=? WHERE case_id=?",
            (action, operator["user_id"], reason, action, _now(), case_id),
        )
        self._audit("MODERATION_DECISION_RECORDED", case_id, "operator", operator["user_id"],
                    {"action": action, "reason": reason, "classifier": case["classifier_result"]})
        return {"ok": True, "case_id": case_id, "action": action}

    def evidence_bundle(self, owner, subject_type: str, subject_id: str) -> dict:
        self.cp.require_owner(owner)
        audit_rows = self.db.query(
            "SELECT event_id, event_type, subject_id, actor_type, actor_id, occurred_at, "
            "payload_hash, previous_event_hash, rights_version, legal_effect "
            "FROM audit_events WHERE subject_id=? ORDER BY occurred_at ASC",
            (subject_id,),
        )
        bundle = {
            "generated_at": _now(),
            "subject_type": subject_type,
            "subject_id": subject_id,
            "audit": [dict(r) for r in audit_rows],
        }
        if subject_type == "game":
            game = dict(self._row("games", "game_id", subject_id, "game not found", "game_not_found"))
            clips = [dict(r) for r in self.db.query("SELECT * FROM clips WHERE source_game_id=?", (subject_id,))]
            bundle["game"] = {
                "game_id": game["game_id"], "game_number": game["game_number"],
                "event_id": game["event_id"], "rights_version": game["rights_version"],
                "verification_status": game["verification_status"],
                "processing_status": game["processing_status"],
                "source_media_asset_id": game["media_asset_id"],
            }
            bundle["clips"] = [
                {"clip_id": c["clip_id"], "start_seconds": c["start_seconds"],
                 "end_seconds": c["end_seconds"], "source_rights_version": c["source_rights_version"],
                 "derived_media_asset_id": c["derived_media_asset_id"]}
                for c in clips
            ]
            if game.get("event_id"):
                rights = self.db.query(
                    "SELECT event_id, version, active, revoked, revocation_reason, created_at "
                    "FROM rights WHERE event_id=? ORDER BY version",
                    (game["event_id"],),
                )
                bundle["rights"] = [dict(r) for r in rights]
        elif subject_type == "clip":
            bundle["clip"] = self.clip_provenance(owner, dict(self._row("clips", "clip_id", subject_id)))
        elif subject_type == "post":
            post = dict(self._row("posts", "post_id", subject_id, "post not found", "post_not_found"))
            bundle["post"] = {
                "post_id": post["post_id"], "publication_status": post["publication_status"],
                "visibility": post["visibility"], "clip_id": post["clip_id"],
            }
        blob = dumps({k: bundle[k] for k in bundle if k != "generated_at"})
        bundle["bundle_hash"] = "sha256:" + hashlib.sha256(blob.encode()).hexdigest()
        return bundle

    def evidence_csv(self, owner, subject_type: str, subject_id: str) -> str:
        bundle = self.evidence_bundle(owner, subject_type, subject_id)
        lines = ["event_id,event_type,subject_id,actor_type,actor_id,occurred_at,payload_hash"]
        for row in bundle["audit"]:
            lines.append(",".join(
                html.escape(str(row.get(k) or ""), quote=True)
                for k in ("event_id", "event_type", "subject_id", "actor_type", "actor_id",
                          "occurred_at", "payload_hash")
            ))
        return "\n".join(lines) + "\n"

    def evidence_html(self, owner, subject_type: str, subject_id: str) -> str:
        bundle = self.evidence_bundle(owner, subject_type, subject_id)
        rows = "".join(
            f"<tr><td>{html.escape(str(r['event_id']))}</td>"
            f"<td>{html.escape(str(r['event_type']))}</td>"
            f"<td>{html.escape(str(r['occurred_at']))}</td>"
            f"<td>{html.escape(str(r['payload_hash']))}</td></tr>"
            for r in bundle["audit"]
        )
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Evidence</title></head>"
            f"<body><h1>Evidence {html.escape(subject_type)} {html.escape(subject_id)}</h1>"
            f"<p>Hash {html.escape(bundle['bundle_hash'])}</p>"
            f"<table border='1'><thead><tr><th>ID</th><th>Type</th><th>When</th><th>Hash</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></body></html>"
        )

    def network_inventory(self) -> dict:
        def count(table):
            row = self.db.query_one(f"SELECT COUNT(*) AS c FROM {table}")
            return int(row["c"] if row else 0)

        return {
            "profiles": count("profiles"),
            "posts": count("posts"),
            "games": count("games"),
            "clips": count("clips"),
            "reactions": count("reactions"),
            "comments": count("comments"),
            "follows": count("follows"),
            "media_assets": count("media_assets"),
            "moderation_cases": count("moderation_cases"),
        }

    def asset_for_playback(self, viewer, asset_id: str):
        asset = dict(self._row("media_assets", "media_asset_id", asset_id, "media not found", "media_not_found"))
        post = self.db.query_one("SELECT * FROM posts WHERE media_asset_id=?", (asset_id,))
        if post and not self.can_see_post(viewer, dict(post)):
            raise ForbiddenError("not authorized", "media_forbidden")
        game = self.db.query_one("SELECT * FROM games WHERE media_asset_id=?", (asset_id,))
        if game and not self.can_see_game(viewer, dict(game)):
            raise ForbiddenError("not authorized", "media_forbidden")
        clip = self.db.query_one("SELECT * FROM clips WHERE derived_media_asset_id=?", (asset_id,))
        if clip and not self.can_see_clip(viewer, dict(clip)):
            raise ForbiddenError("not authorized", "media_forbidden")
        if not post and not game and not clip:
            owner = self.ensure_profile(viewer) if viewer else None
            if not owner or owner["profile_id"] != asset["owner_profile_id"]:
                if not self._staff(viewer):
                    raise ForbiddenError("not authorized", "media_forbidden")
        if hasattr(self.provider, "remember_asset"):
            self.provider.remember_asset(
                asset.get("provider_uid"),
                kind=asset.get("kind"),
                duration_seconds=asset.get("duration_seconds"),
                status=asset.get("status") or "ready",
            )
        meta = {}
        try:
            meta = self.provider.playback_metadata(asset["provider_uid"]) or {}
        except ProviderError:
            meta = {}
        seconds = int(asset["duration_seconds"] or meta.get("duration_seconds") or 8)
        return asset, max(2, min(seconds, 600))
