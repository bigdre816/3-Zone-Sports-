"""Canonical City place layer. Getting There requires city_place_id.

Sports events resolve through the same ids when a home venue or venue-name
alias matches. Coordinates live on the place row so planning never geocodes
a slogan. Seeded KC sports anchors are public stadium locations.
"""

from __future__ import annotations

import time

from ..db import dumps, loads

# Public stadium locations (not secret). Used as KC sports vertical anchors.
KC_SPORTS_ANCHORS = (
    {
        "city_place_id": "plc_kc_arrowhead",
        "name": "GEHA Field at Arrowhead Stadium",
        "address": "1 Arrowhead Dr, Kansas City, MO 64129",
        "locality": "Kansas City",
        "region": "MO",
        "postal_code": "64129",
        "country": "US",
        "latitude": 39.0489,
        "longitude": -94.4839,
        "timezone": "America/Chicago",
        "category": "sports_venue",
        "vertical": "sports",
        "aliases": (
            "arrowhead",
            "arrowhead stadium",
            "geha field",
            "geha field at arrowhead stadium",
            "chiefs stadium",
        ),
        "google_place_id": None,
        "home_team_ids": ("team_nfl_kc_chiefs",),
    },
    {
        "city_place_id": "plc_kc_kauffman",
        "name": "Kauffman Stadium",
        "address": "1 Royal Way, Kansas City, MO 64129",
        "locality": "Kansas City",
        "region": "MO",
        "postal_code": "64129",
        "country": "US",
        "latitude": 39.0516,
        "longitude": -94.4803,
        "timezone": "America/Chicago",
        "category": "sports_venue",
        "vertical": "sports",
        "aliases": (
            "kauffman",
            "kauffman stadium",
            "kauffman stadium kansas city",
            "royals stadium",
            "the k",
        ),
        "google_place_id": None,
        "home_team_ids": ("team_mlb_kc_royals",),
    },
)


def _now() -> float:
    return time.time()


def _norm(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def _words(text: str | None) -> list[str]:
    buf = []
    for ch in (text or "").lower():
        buf.append(ch if ch.isalnum() else " ")
    return "".join(buf).split()


def _alias_in_venue(alias: str, key: str) -> bool:
    """Whole-phrase match so short aliases cannot prefix a different venue."""
    alias_words = _words(alias)
    if len(alias_words) < 2:
        return False
    key_words = _words(key)
    span = len(alias_words)
    if span > len(key_words):
        return False
    return any(key_words[i:i + span] == alias_words for i in range(len(key_words) - span + 1))


class CityPlaceService:
    """Read/seed canonical places. Never invents a destination."""

    def __init__(self, db):
        self.db = db

    def ensure_seeded(self) -> int:
        """Idempotent seed of KC sports anchors + team/alias links."""
        stamp = _now()
        written = 0
        for spec in KC_SPORTS_ANCHORS:
            existing = self.db.query_one(
                "SELECT city_place_id FROM city_places WHERE city_place_id=?",
                (spec["city_place_id"],),
            )
            if not existing:
                self.db.execute(
                    "INSERT INTO city_places(city_place_id,name,address,locality,region,postal_code,"
                    "country,latitude,longitude,timezone,category,vertical,aliases,google_place_id,"
                    "status,home_team_ids,created_at,recorded_at,legal_effect) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        spec["city_place_id"], spec["name"], spec["address"], spec["locality"],
                        spec["region"], spec["postal_code"], spec["country"], spec["latitude"],
                        spec["longitude"], spec["timezone"], spec["category"], spec["vertical"],
                        dumps(list(spec["aliases"])), spec["google_place_id"], "active",
                        dumps(list(spec["home_team_ids"])), stamp, stamp, "provenance_only",
                    ),
                )
                written += 1
            for team_id in spec["home_team_ids"]:
                self._link(spec["city_place_id"], "home_team", team_id, stamp)
            for alias in spec["aliases"]:
                self._link(spec["city_place_id"], "venue_alias", _norm(alias), stamp)
        return written

    def _link(self, city_place_id: str, subject_type: str, subject_key: str, stamp: float) -> None:
        if not subject_key:
            return
        self.db.execute(
            "INSERT OR IGNORE INTO city_place_links(link_id,city_place_id,subject_type,subject_key,recorded_at) "
            "VALUES (?,?,?,?,?)",
            (f"lnk_{subject_type}_{subject_key}"[:80], city_place_id, subject_type, subject_key, stamp),
        )

    def get(self, city_place_id: str) -> dict | None:
        if not city_place_id:
            return None
        row = self.db.query_one(
            "SELECT * FROM city_places WHERE city_place_id=? AND status='active'",
            (city_place_id,),
        )
        return self._public(row) if row else None

    def list_places(self, *, vertical: str | None = None) -> list[dict]:
        if vertical:
            rows = self.db.query(
                "SELECT * FROM city_places WHERE status='active' AND vertical=? ORDER BY name",
                (vertical,),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM city_places WHERE status='active' ORDER BY name"
            )
        return [self._public(row) for row in rows]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS c FROM city_places WHERE status='active'")
        return int(row["c"]) if row else 0

    def resolve_for_home_team(self, team_id: str | None) -> dict | None:
        if not team_id:
            return None
        row = self.db.query_one(
            "SELECT p.* FROM city_place_links l JOIN city_places p ON p.city_place_id=l.city_place_id "
            "WHERE l.subject_type='home_team' AND l.subject_key=? AND p.status='active'",
            (team_id,),
        )
        return self._public(row) if row else None

    def resolve_for_alias(self, text: str | None) -> dict | None:
        key = _norm(text)
        if not key:
            return None
        row = self.db.query_one(
            "SELECT p.* FROM city_place_links l JOIN city_places p ON p.city_place_id=l.city_place_id "
            "WHERE l.subject_type='venue_alias' AND l.subject_key=? AND p.status='active'",
            (key,),
        )
        if row:
            return self._public(row)
        # Loose contains match against stored aliases when the feed venue is longer.
        for place in self.list_places():
            aliases = [_norm(a) for a in (place.get("aliases") or [])]
            name = _norm(place.get("name"))
            if key == name or key in aliases:
                return place
            if any(_alias_in_venue(alias, key) for alias in aliases):
                return place
        return None

    def resolve_for_game(self, game: dict | None) -> dict | None:
        """Home-team stadium when the home side is a linked team; else venue alias."""
        if not isinstance(game, dict):
            return None
        home_id = (game.get("home") or {}).get("team_id")
        by_home = self.resolve_for_home_team(home_id)
        if by_home:
            return by_home
        return self.resolve_for_alias(game.get("venue"))

    def resolve_for_schedule(self, row: dict | None) -> dict | None:
        if not isinstance(row, dict):
            return None
        existing = row.get("city_place_id")
        if existing:
            return self.get(existing)
        return self.resolve_for_alias(row.get("location"))

    def annotate_game(self, game: dict) -> dict:
        item = dict(game)
        place = self.resolve_for_game(item)
        item["city_place_id"] = place["city_place_id"] if place else None
        item["city_place"] = self._summary(place) if place else None
        return item

    def annotate_sports_payload(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return payload
        if isinstance(payload.get("games"), list):
            payload["games"] = [self.annotate_game(g) for g in payload["games"]]
        sections = payload.get("sections")
        if isinstance(sections, dict):
            payload["sections"] = {
                key: [self.annotate_game(g) for g in (value or [])] if isinstance(value, list) else value
                for key, value in sections.items()
            }
        my_zone = payload.get("my_zone")
        if isinstance(my_zone, dict):
            payload["my_zone"] = {
                key: [self.annotate_game(g) for g in (value or [])] if isinstance(value, list) else value
                for key, value in my_zone.items()
            }
        member = payload.get("member")
        if isinstance(member, dict):
            for key in ("live_now", "upcoming", "finals"):
                if isinstance(member.get(key), list):
                    member[key] = [self.annotate_game(g) for g in member[key]]
            cards = member.get("my_teams")
            if isinstance(cards, list):
                annotated = []
                for card in cards:
                    item = dict(card)
                    if isinstance(item.get("game"), dict):
                        item["game"] = self.annotate_game(item["game"])
                    annotated.append(item)
                member["my_teams"] = annotated
        return payload

    def annotate_schedules(self, rows: list) -> list[dict]:
        out = []
        for row in rows:
            item = dict(row)
            place = self.resolve_for_schedule(item)
            item["city_place_id"] = place["city_place_id"] if place else None
            item["city_place"] = self._summary(place) if place else None
            out.append(item)
        return out

    def _public(self, row) -> dict:
        data = dict(row)
        aliases = loads(data.get("aliases"), []) or []
        home_ids = loads(data.get("home_team_ids"), []) or []
        return {
            "city_place_id": data["city_place_id"],
            "name": data["name"],
            "address": data["address"],
            "locality": data.get("locality"),
            "region": data.get("region"),
            "postal_code": data.get("postal_code"),
            "country": data.get("country") or "US",
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "timezone": data.get("timezone") or "America/Chicago",
            "category": data.get("category"),
            "vertical": data.get("vertical"),
            "aliases": aliases,
            "home_team_ids": home_ids,
            "status": data.get("status") or "active",
            "legal_effect": data.get("legal_effect") or "provenance_only",
        }

    @staticmethod
    def _summary(place: dict | None) -> dict | None:
        if not place:
            return None
        return {
            "city_place_id": place["city_place_id"],
            "name": place["name"],
            "address": place["address"],
            "timezone": place["timezone"],
        }
