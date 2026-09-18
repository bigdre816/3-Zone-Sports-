"""Shared sports-feed cache, coordinated polling, and member/public snapshots."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..db import dumps, loads
from .catalog import (
    DEFAULT_FOLLOW_TEAM_IDS,
    LOCAL_PRIORITY_TEAM_IDS,
    PRO_TEAMS,
    catalog_public,
    default_provider_ids,
    match_provider_team,
    team_by_id,
)
from .client import BalldontlieClient, FeedClientError, NotConfiguredError
from .normalize import CHICAGO, iso_utc, normalize_game

LEAGUES = ("NFL", "MLB", "NBA")
PROVIDER = "balldontlie"
IN_PROGRESS_POLL_SECONDS = 20
SCHEDULE_POLL_SECONDS = 300
TEAM_TTL_SECONDS = 12 * 3600
FRESH_IN_PROGRESS_SECONDS = 45
FRESH_SCHEDULE_SECONDS = 600
DATE_WINDOW_PAST_DAYS = 1
DATE_WINDOW_FUTURE_DAYS = 6

RIGHTS_NOTE = (
    "Scoreboard and schedule facts from the sports data provider. "
    "This is not a streaming entitlement, media lease, or LIVE_PUBLIC grant."
)

GAPS = {
    "college": {
        "status": "not_configured",
        "reason": (
            "BALLDONTLIE covers NFL, MLB, and NBA only. College games stay on the "
            "Three-Zone catalog and operator schedule-import path."
        ),
    },
    "high_school": {
        "status": "not_configured",
        "reason": (
            "High-school and youth games are not on BALLDONTLIE. They remain on the "
            "existing Kansas City school/team catalog, CSV schedules, and live events."
        ),
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def chicago_dates(now: datetime | None = None) -> list[str]:
    stamp = (now or _now()).astimezone(CHICAGO).date()
    days = [
        stamp + timedelta(days=offset)
        for offset in range(-DATE_WINDOW_PAST_DAYS, DATE_WINDOW_FUTURE_DAYS + 1)
    ]
    return [day.isoformat() for day in days]


def _iso_ts(ts: float | None) -> str | None:
    if ts is None:
        return None
    return iso_utc(datetime.fromtimestamp(ts, tz=timezone.utc))


def _freshness_for(last_ok: float | None, *, in_progress: bool, configured: bool, now_ts: float) -> str:
    if not configured:
        return "not_configured"
    if last_ok is None:
        return "unavailable"
    ttl = FRESH_IN_PROGRESS_SECONDS if in_progress else FRESH_SCHEDULE_SECONDS
    if (now_ts - last_ok) <= ttl:
        return "fresh"
    return "stale"


class SportsFeedService:
    """One process-wide feed cache. Never invents demo scores on failure."""

    def __init__(
        self,
        config,
        db,
        client: BalldontlieClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.config = config
        self.db = db
        key = getattr(config, "balldontlie_api_key", "") or ""
        self.client = client if client is not None else BalldontlieClient(key)
        self._clock = clock or _now
        self._sleep = sleeper or time.sleep
        self._lock = threading.RLock()
        self._poller: threading.Thread | None = None
        self._stop = threading.Event()
        self._mem: dict[str, dict] = {}
        self._provider_ids: dict[str, str] = dict(default_provider_ids())
        self._teams_fetched_at: float | None = None
        self._load_persisted()

    @property
    def configured(self) -> bool:
        return bool(getattr(self.client, "configured", False))

    def start_poller(self) -> None:
        if self._poller and self._poller.is_alive():
            return
        self._stop.clear()
        self._poller = threading.Thread(target=self._poll_loop, name="sports-feeds", daemon=True)
        self._poller.start()

    def stop_poller(self) -> None:
        self._stop.set()

    def health(self) -> dict:
        now_ts = self._clock().timestamp()
        leagues = {}
        any_in_progress = False
        last_ok = None
        last_attempt = None
        for league in LEAGUES:
            row = self._mem.get(league) or {}
            games = list(row.get("games") or [])
            in_progress = any(g.get("status") == "in_progress" for g in games)
            if in_progress:
                any_in_progress = True
            ok = row.get("last_successful_fetch")
            attempt = row.get("last_attempt_at") if row.get("last_attempt_at") is not None else row.get("updated_at")
            if ok is not None:
                last_ok = ok if last_ok is None else max(last_ok, ok)
            if attempt is not None:
                last_attempt = attempt if last_attempt is None else max(last_attempt, attempt)
            leagues[league] = {
                "freshness": _freshness_for(
                    ok, in_progress=in_progress, configured=self.configured, now_ts=now_ts,
                ),
                "last_successful_fetch": _iso_ts(ok),
                "last_attempt_at": _iso_ts(attempt),
                "game_count": len(games),
                "last_error_class": row.get("last_error_class"),
            }
        freshness = _freshness_for(
            last_ok, in_progress=any_in_progress, configured=self.configured, now_ts=now_ts,
        )
        return {
            "provider": PROVIDER,
            "configured": self.configured,
            "freshness": freshness,
            "last_successful_fetch": _iso_ts(last_ok),
            "last_attempt_at": _iso_ts(last_attempt),
            "leagues": leagues,
            "rights_note": RIGHTS_NOTE,
            "gaps": GAPS,
        }

    def snapshot(
        self,
        *,
        followed_team_ids: list[str] | None = None,
        sports: list[str] | None = None,
        bucket: str | None = None,
        team_id: str | None = None,
        league: str | None = None,
        refresh: bool = False,
    ) -> dict:
        if refresh or self._should_refresh():
            self.refresh()
        games = self._all_games()
        if team_id and bucket != "browse":
            spec = team_by_id(team_id)
            games = [g for g in games if self._involves_team(g, team_id)]
            team = None
            if spec:
                team = {
                    "team_id": spec.team_id,
                    "name": spec.name,
                    "league": spec.league,
                    "market": spec.market,
                }
            payload = self._envelope(games, bucket="team")
            payload["team"] = team
            if spec is None:
                payload["team"] = {"team_id": team_id, "name": None, "league": None, "market": None}
            return payload

        follows = [tid for tid in (followed_team_ids or []) if tid] or list(DEFAULT_FOLLOW_TEAM_IDS)
        follow_set = set(follows)
        sports = [s.lower() for s in (sports or []) if s]
        local = [g for g in games if self._is_local(g)]
        in_progress = [g for g in games if g.get("status") == "in_progress"]
        upcoming = [g for g in games if g.get("status") in ("scheduled", "delayed", "postponed")]
        finals = [g for g in games if g.get("status") == "final"]
        nba = [g for g in games if g.get("league") == "NBA"]
        preferred_nba = [g for g in nba if self._involves_any(g, follow_set)]
        cares_nba = "basketball" in sports or any(
            (team_by_id(tid) and team_by_id(tid).league == "NBA") for tid in follows
        )
        live_now = self._sort_games([
            g for g in in_progress
            if self._involves_any(g, follow_set) or (g.get("league") == "NBA" and cares_nba)
        ])
        upcoming_followed = self._sort_games([g for g in upcoming if self._involves_any(g, follow_set)])[:8]
        finals_followed = self._sort_games([g for g in finals if self._involves_any(g, follow_set)])[:8]
        my_teams = [self._team_card(tid, games) for tid in follows]
        sections = {
            "local": self._sort_games(local),
            "in_progress": self._sort_games(in_progress),
            "upcoming": self._sort_games(upcoming),
            "finals": self._sort_games(finals),
            "nba_national": self._sort_games(nba),
            "nba_preferred": self._sort_games(preferred_nba),
        }
        member = {
            "my_teams": my_teams,
            "live_now": live_now,
            "upcoming": upcoming_followed,
            "finals": finals_followed,
            "followed_team_ids": follows,
        }
        if bucket in ("upcoming", "finals"):
            payload = self._envelope(member[bucket], bucket=bucket)
            payload["member"] = member
            return payload
        if bucket in ("live_now", "in_progress"):
            payload = self._envelope(live_now, bucket="live_now")
            payload["member"] = member
            return payload
        if bucket in ("local", "nba_national"):
            return self._envelope(sections[bucket], bucket=bucket)
        if bucket == "browse":
            browsed = list(games)
            if league:
                browsed = [g for g in browsed if (g.get("league") or "").upper() == league.upper()]
            if team_id:
                browsed = [g for g in browsed if self._involves_team(g, team_id)]
            payload = self._envelope(self._sort_games(browsed)[:20], bucket="browse")
            payload["browse"] = {"league": (league or "").upper() or None, "team_id": team_id}
            payload["teams"] = catalog_public()
            payload["member"] = member
            return payload
        payload = self._envelope(self._sort_games(games), bucket=bucket or "all")
        payload["sections"] = sections
        show_national = cares_nba or not preferred_nba
        payload["my_zone"] = {
            "local": sections["local"],
            "in_progress": sections["in_progress"],
            "preferred_nba": sections["nba_preferred"],
            "nba_national": sections["nba_national"] if show_national else [],
        }
        payload["member"] = member
        payload["teams"] = catalog_public()
        return payload

    def refresh(self, force: bool = False) -> dict:
        with self._lock:
            if not self.configured:
                for league in LEAGUES:
                    self._mem.setdefault(league, {
                        "games": [],
                        "freshness": "not_configured",
                        "last_successful_fetch": None,
                        "last_attempt_at": None,
                        "last_error_class": None,
                    })
                return self.health()
            now = self._clock()
            self._ensure_provider_ids(now, force=force)
            dates = chicago_dates(now)
            for league in LEAGUES:
                try:
                    team_ids = None
                    if league in ("NFL", "MLB"):
                        mapped = [
                            self._provider_ids[spec.team_id]
                            for spec in PRO_TEAMS
                            if spec.league == league and spec.team_id in self._provider_ids
                        ]
                        team_ids = mapped or None
                    raw_games = self.client.list_games(league, dates=dates, team_ids=team_ids)
                    games = []
                    for raw in raw_games:
                        item = normalize_game(league, raw, retrieved_at=now)
                        if item:
                            games.append(item)
                    self._store_league(league, games, now, error_class=None)
                except NotConfiguredError:
                    self._store_league(league, None, now, error_class="not_configured")
                except FeedClientError as exc:
                    self._store_league(league, None, now, error_class=exc.kind)
            return self.health()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception:
                pass
            wait = IN_PROGRESS_POLL_SECONDS if self._has_in_progress() else SCHEDULE_POLL_SECONDS
            if not self.configured:
                wait = SCHEDULE_POLL_SECONDS
            self._stop.wait(wait)

    def _should_refresh(self) -> bool:
        if not self.configured:
            return False
        now_ts = self._clock().timestamp()
        last_ok = None
        in_progress = False
        for league in LEAGUES:
            row = self._mem.get(league) or {}
            ok = row.get("last_successful_fetch")
            if ok is not None:
                last_ok = ok if last_ok is None else max(last_ok, ok)
            if any(g.get("status") == "in_progress" for g in (row.get("games") or [])):
                in_progress = True
        if last_ok is None:
            return True
        ttl = FRESH_IN_PROGRESS_SECONDS if in_progress else FRESH_SCHEDULE_SECONDS
        return (now_ts - last_ok) > ttl

    def _has_in_progress(self) -> bool:
        return any(
            g.get("status") == "in_progress"
            for row in self._mem.values()
            for g in (row.get("games") or [])
        )

    def _ensure_provider_ids(self, now: datetime, force: bool = False) -> None:
        now_ts = now.timestamp()
        if (
            not force
            and self._provider_ids
            and self._teams_fetched_at
            and (now_ts - self._teams_fetched_at) < TEAM_TTL_SECONDS
        ):
            return
        fetched_any = False
        for league in LEAGUES:
            try:
                teams = self.client.list_teams(league)
            except FeedClientError:
                continue
            fetched_any = True
            for raw in teams:
                spec = match_provider_team(league, raw)
                if spec and raw.get("id") is not None:
                    pid = str(raw["id"])
                    self._provider_ids[spec.team_id] = pid
                    self._persist_team_map(spec.team_id, league, pid, spec.name)
        if fetched_any:
            self._teams_fetched_at = now_ts

    def _store_league(self, league: str, games: list[dict] | None, now: datetime, error_class: str | None) -> None:
        existing = self._mem.get(league) or {}
        prev_games = list(existing.get("games") or [])
        prev_ok = existing.get("last_successful_fetch")
        now_ts = now.timestamp()
        if games is not None:
            stored = games
            last_ok = now_ts
            err = None
        else:
            stored = prev_games  # keep last good snapshot; never substitute demo scores
            last_ok = prev_ok
            err = error_class
        in_progress = any(g.get("status") == "in_progress" for g in stored)
        freshness = _freshness_for(
            last_ok, in_progress=in_progress, configured=self.configured, now_ts=now_ts,
        )
        if error_class == "not_configured":
            freshness = "not_configured"
            stored = []
            last_ok = None
        row = {
            "games": stored,
            "freshness": freshness,
            "last_successful_fetch": last_ok,
            "last_attempt_at": now_ts,
            "last_error_class": err,
            "updated_at": now_ts,
        }
        self._mem[league] = row
        self._persist_snapshot(league, row)

    def _all_games(self) -> list[dict]:
        games = []
        for league in LEAGUES:
            row = self._mem.get(league) or {}
            freshness = row.get("freshness") or "unavailable"
            for game in row.get("games") or []:
                item = dict(game)
                item["freshness"] = freshness
                games.append(item)
        return games

    def _envelope(self, games: list[dict], *, bucket: str) -> dict:
        health = self.health()
        return {
            "provider": PROVIDER,
            "bucket": bucket,
            "freshness": health["freshness"],
            "last_successful_fetch": health["last_successful_fetch"],
            "last_attempt_at": health["last_attempt_at"],
            "configured": health["configured"],
            "games": games,
            "leagues": health["leagues"],
            "rights_note": RIGHTS_NOTE,
            "gaps": GAPS,
            "market": {
                "name": "Kansas City MO/KS + Overland Park",
                "timezone": "America/Chicago",
                "priority_teams": sorted(LOCAL_PRIORITY_TEAM_IDS),
            },
        }

    def _team_card(self, team_id: str, games: list[dict]) -> dict:
        spec = team_by_id(team_id)
        involving = [g for g in games if self._involves_team(g, team_id)]
        headline = None
        for status in ("in_progress", "scheduled", "delayed", "postponed", "final"):
            for game in self._sort_games(involving):
                if game.get("status") == status:
                    headline = game
                    break
            if headline:
                break
        if headline is None and involving:
            headline = involving[0]
        return {
            "team_id": team_id,
            "name": spec.name if spec else team_id,
            "league": spec.league if spec else None,
            "abbreviation": spec.abbreviations[0] if spec and spec.abbreviations else None,
            "game": headline,
        }

    def _is_local(self, game: dict) -> bool:
        return self._involves_any(game, LOCAL_PRIORITY_TEAM_IDS)

    def _involves_team(self, game: dict, team_id: str) -> bool:
        home = (game.get("home") or {}).get("team_id")
        away = (game.get("away") or {}).get("team_id")
        return team_id in {home, away}

    def _involves_any(self, game: dict, team_ids) -> bool:
        ids = set(team_ids)
        home = (game.get("home") or {}).get("team_id")
        away = (game.get("away") or {}).get("team_id")
        return home in ids or away in ids

    def _sort_games(self, games: list[dict]) -> list[dict]:
        rank = {"in_progress": 0, "scheduled": 1, "delayed": 2, "postponed": 3, "final": 4}

        def key(game: dict):
            local = 0 if self._is_local(game) else 1
            status_rank = rank.get(game.get("status") or "", 9)
            start = game.get("scheduled_start") or ""
            league_rank = {"NFL": 0, "MLB": 1, "NBA": 2}.get(game.get("league") or "", 9)
            return (local, status_rank, start, league_rank, game.get("external_game_id") or "")

        return sorted(games, key=key)

    def _load_persisted(self) -> None:
        try:
            rows = self.db.query("SELECT * FROM sports_feed_snapshots")
        except Exception:
            return
        for row in rows:
            league = row["league"]
            games = loads(row["payload"], [])
            if not isinstance(games, list):
                games = []
            try:
                attempt = row["last_attempt_at"]
            except (KeyError, IndexError):
                attempt = None
            if attempt is None:
                attempt = row["updated_at"]
            self._mem[league] = {
                "games": games,
                "freshness": row["freshness"],
                "last_successful_fetch": row["last_successful_fetch"],
                "last_attempt_at": attempt,
                "last_error_class": row["last_error_class"],
                "updated_at": row["updated_at"],
            }
        try:
            maps = self.db.query("SELECT team_id, provider_team_id FROM sports_feed_teams WHERE provider_team_id IS NOT NULL")
        except Exception:
            maps = []
        for row in maps:
            if row["team_id"] and row["provider_team_id"]:
                self._provider_ids[row["team_id"]] = str(row["provider_team_id"])

    def _persist_snapshot(self, league: str, row: dict) -> None:
        try:
            self.db.execute("DELETE FROM sports_feed_snapshots WHERE league=?", (league,))
            self.db.execute(
                "INSERT INTO sports_feed_snapshots(snapshot_id, provider, league, payload, freshness, "
                "last_successful_fetch, last_attempt_at, last_error_class, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"bdl:{league.lower()}",
                    PROVIDER,
                    league,
                    dumps(row.get("games") or []),
                    row.get("freshness") or "unavailable",
                    row.get("last_successful_fetch"),
                    row.get("last_attempt_at") if row.get("last_attempt_at") is not None else row.get("updated_at"),
                    row.get("last_error_class"),
                    row.get("updated_at") or time.time(),
                ),
            )
        except Exception:
            pass

    def _persist_team_map(self, team_id: str, league: str, provider_team_id: str, name: str) -> None:
        try:
            self.db.execute("DELETE FROM sports_feed_teams WHERE team_id=?", (team_id,))
            self.db.execute(
                "INSERT INTO sports_feed_teams(team_id, league, provider, provider_team_id, name, "
                "abbreviation, aliases, market, priority, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    team_id, league, PROVIDER, provider_team_id, name, None, "[]", None, 100,
                    self._clock().timestamp(),
                ),
            )
        except Exception:
            pass
