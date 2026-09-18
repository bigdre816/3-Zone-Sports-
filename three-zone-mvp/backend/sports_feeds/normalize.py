"""Normalize BALLDONTLIE game payloads into the Three-Zone sports-feed shape.

Unknown values become JSON null. Dates are labeled; America/Chicago is the
display timezone for the Kansas City / Overland Park market.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .catalog import match_provider_team

CHICAGO = ZoneInfo("America/Chicago")
PROVIDER = "balldontlie"
KNOWN_STATUS = frozenset({
    "scheduled", "in_progress", "final", "postponed", "canceled",
    "delayed", "suspended", "abandoned",
})
_STATUS_ALIASES = {
    "cancelled": "canceled",
    "cancel": "canceled",
    "complete": "final",
    "completed": "final",
    "closed": "final",
    "status_final": "final",
    "status_in_progress": "in_progress",
    "status_scheduled": "scheduled",
    "halftime": "in_progress",
    "end of period": "in_progress",
    "end of inning": "in_progress",
}


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def chicago_fields(dt: datetime | None) -> dict:
    if dt is None:
        return {
            "scheduled_start": None,
            "scheduled_start_chicago": None,
            "display_local": None,
            "timezone": "America/Chicago",
        }
    utc = dt.astimezone(timezone.utc)
    local = utc.astimezone(CHICAGO)
    hour = local.strftime("%I").lstrip("0") or "12"
    return {
        "scheduled_start": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scheduled_start_chicago": local.isoformat(timespec="seconds"),
        "display_local": f"{local.strftime('%a, %b')} {local.day} · {hour}:{local.strftime('%M %p')} CT",
        "timezone": "America/Chicago",
    }


def parse_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _status(raw: dict) -> str | None:
    state = _str_or_none(raw.get("status_state"))
    if state:
        mapped = _STATUS_ALIASES.get(state.lower(), state.lower())
        return mapped if mapped in KNOWN_STATUS else None
    status = _str_or_none(raw.get("status"))
    if not status:
        return None
    lowered = status.lower().replace("-", "_")
    mapped = _STATUS_ALIASES.get(lowered, lowered)
    if mapped in KNOWN_STATUS:
        return mapped
    if "final" in lowered:
        return "final"
    if "progress" in lowered or "qtr" in lowered or "quarter" in lowered or "half" in lowered:
        return "in_progress"
    if "postpone" in lowered:
        return "postponed"
    if "delay" in lowered:
        return "delayed"
    if "suspend" in lowered:
        return "suspended"
    if "cancel" in lowered:
        return "canceled"
    if any(ch.isdigit() for ch in status) and ("am" in lowered or "pm" in lowered):
        return "scheduled"
    return None


def _side(league: str, raw_team: dict | None, score) -> dict:
    team = raw_team if isinstance(raw_team, dict) else {}
    spec = match_provider_team(league, team)
    name = (
        _str_or_none(team.get("full_name"))
        or _str_or_none(team.get("display_name"))
        or _str_or_none(team.get("name"))
    )
    abbr = _str_or_none(team.get("abbreviation"))
    provider_id = team.get("id")
    return {
        "name": name,
        "abbreviation": abbr,
        "provider_team_id": str(provider_id) if provider_id is not None else None,
        "team_id": spec.team_id if spec else None,
        "score": _int_or_none(score),
    }


def _home_away(league: str, raw: dict) -> tuple[dict, dict]:
    home_raw = raw.get("home_team") if isinstance(raw.get("home_team"), dict) else {}
    away_raw = raw.get("away_team") if isinstance(raw.get("away_team"), dict) else None
    if away_raw is None:
        away_raw = raw.get("visitor_team") if isinstance(raw.get("visitor_team"), dict) else {}
    if league == "MLB":
        home_data = raw.get("home_team_data") if isinstance(raw.get("home_team_data"), dict) else {}
        away_data = raw.get("away_team_data") if isinstance(raw.get("away_team_data"), dict) else {}
        home_score = home_data.get("runs")
        away_score = away_data.get("runs")
    else:
        home_score = raw.get("home_team_score")
        away_score = raw.get("away_team_score")
        if away_score is None:
            away_score = raw.get("visitor_team_score")
    return _side(league, home_raw, home_score), _side(league, away_raw, away_score)


def _clock(raw: dict) -> str | None:
    for key in ("display_clock", "clock_display", "time", "clock"):
        value = raw.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)) and key == "clock" and value == 0:
            status = _status(raw)
            if status in ("scheduled", "final"):
                return None
        text = str(value).strip()
        if not text or text in (".", "-"):
            continue
        if text.lower() in ("final", "0:00", "0.00"):
            status = _status(raw)
            if status == "final":
                return None
        return text
    return None


def _period_fields(league: str, raw: dict) -> dict:
    period = _int_or_none(raw.get("period"))
    detail = _str_or_none(raw.get("period_detail"))
    if league == "MLB":
        return {"period": None, "inning": period, "period_detail": detail}
    return {"period": period, "inning": None, "period_detail": detail}


def _venue(raw: dict) -> str | None:
    venue = raw.get("venue")
    if isinstance(venue, dict):
        return _str_or_none(venue.get("name") or venue.get("full_name"))
    return _str_or_none(venue)


def normalize_game(league: str, raw: dict, *, retrieved_at: datetime) -> dict | None:
    if not isinstance(raw, dict):
        return None
    provider_game_id = raw.get("id")
    if provider_game_id is None:
        return None
    gid = str(provider_game_id)
    home, away = _home_away(league, raw)
    start = parse_datetime(raw.get("datetime") or raw.get("date"))
    chicago = chicago_fields(start)
    status = _status(raw)
    period_fields = _period_fields(league, raw)
    updated = parse_datetime(raw.get("updated_at") or raw.get("provider_updated_at"))
    return {
        "provider": PROVIDER,
        "league": league,
        "provider_game_id": gid,
        "external_game_id": f"bdl:{league.lower()}:{gid}",
        "home": home,
        "away": away,
        "status": status,
        "period": period_fields["period"],
        "inning": period_fields["inning"],
        "period_detail": period_fields["period_detail"],
        "clock": _clock(raw),
        "scheduled_start": chicago["scheduled_start"],
        "scheduled_start_chicago": chicago["scheduled_start_chicago"],
        "display_local": chicago["display_local"],
        "timezone": chicago["timezone"],
        "venue": _venue(raw),
        "source_ref": f"balldontlie:{league.lower()}:{gid}",
        "provider_updated_at": iso_utc(updated),
        "retrieved_at": iso_utc(retrieved_at),
        "postseason": bool(raw["postseason"]) if isinstance(raw.get("postseason"), bool) else None,
        "season": _int_or_none(raw.get("season")),
        "week": _int_or_none(raw.get("week")),
    }
