"""Canonical professional team catalog for Kansas City + NBA preferences.

Provider team IDs are resolved at runtime from BALLDONTLIE `/teams` payloads.
They are never treated as streaming/media rights identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProTeam:
    team_id: str
    league: str
    name: str
    abbreviations: tuple[str, ...]
    aliases: tuple[str, ...]
    location: str
    market: str = "national"
    priority: int = 100
    sport: str = ""
    level: str = "professional"
    org_id: str = ""
    provider_team_id: str | None = None


def _nfl(**kwargs) -> ProTeam:
    return ProTeam(league="NFL", sport="football", org_id="org_nfl", **kwargs)


def _mlb(**kwargs) -> ProTeam:
    return ProTeam(league="MLB", sport="baseball", org_id="org_mlb", **kwargs)


def _nba(**kwargs) -> ProTeam:
    return ProTeam(league="NBA", sport="basketball", org_id="org_nba", **kwargs)


PRO_TEAMS: tuple[ProTeam, ...] = (
    _nfl(
        team_id="team_nfl_kc_chiefs",
        name="Kansas City Chiefs",
        abbreviations=("KC", "KAN"),
        aliases=("chiefs", "kansas city chiefs"),
        location="Kansas City",
        market="kansas_city",
        priority=1,
        provider_team_id="14",
    ),
    _mlb(
        team_id="team_mlb_kc_royals",
        name="Kansas City Royals",
        abbreviations=("KC", "KCR"),
        aliases=("royals", "kansas city royals"),
        location="Kansas City",
        market="kansas_city",
        priority=1,
        provider_team_id="12",
    ),
    _nba(team_id="team_nba_atl", name="Atlanta Hawks", abbreviations=("ATL",), aliases=("hawks",), location="Atlanta"),
    _nba(team_id="team_nba_bos", name="Boston Celtics", abbreviations=("BOS",), aliases=("celtics",), location="Boston"),
    _nba(team_id="team_nba_bkn", name="Brooklyn Nets", abbreviations=("BKN", "BRK"), aliases=("nets",), location="Brooklyn"),
    _nba(team_id="team_nba_cha", name="Charlotte Hornets", abbreviations=("CHA",), aliases=("hornets",), location="Charlotte"),
    _nba(team_id="team_nba_chi", name="Chicago Bulls", abbreviations=("CHI",), aliases=("bulls",), location="Chicago"),
    _nba(team_id="team_nba_cle", name="Cleveland Cavaliers", abbreviations=("CLE",), aliases=("cavaliers", "cavs"), location="Cleveland"),
    _nba(team_id="team_nba_dal", name="Dallas Mavericks", abbreviations=("DAL",), aliases=("mavericks", "mavs"), location="Dallas"),
    _nba(team_id="team_nba_den", name="Denver Nuggets", abbreviations=("DEN",), aliases=("nuggets",), location="Denver"),
    _nba(team_id="team_nba_det", name="Detroit Pistons", abbreviations=("DET",), aliases=("pistons",), location="Detroit"),
    _nba(team_id="team_nba_gsw", name="Golden State Warriors", abbreviations=("GSW", "GS"), aliases=("warriors",), location="Golden State"),
    _nba(team_id="team_nba_hou", name="Houston Rockets", abbreviations=("HOU",), aliases=("rockets",), location="Houston"),
    _nba(team_id="team_nba_ind", name="Indiana Pacers", abbreviations=("IND",), aliases=("pacers",), location="Indiana"),
    _nba(team_id="team_nba_lac", name="LA Clippers", abbreviations=("LAC",), aliases=("clippers", "la clippers", "los angeles clippers"), location="Los Angeles"),
    _nba(team_id="team_nba_lal", name="Los Angeles Lakers", abbreviations=("LAL",), aliases=("lakers",), location="Los Angeles"),
    _nba(team_id="team_nba_mem", name="Memphis Grizzlies", abbreviations=("MEM",), aliases=("grizzlies",), location="Memphis"),
    _nba(team_id="team_nba_mia", name="Miami Heat", abbreviations=("MIA",), aliases=("heat",), location="Miami"),
    _nba(team_id="team_nba_mil", name="Milwaukee Bucks", abbreviations=("MIL",), aliases=("bucks",), location="Milwaukee"),
    _nba(team_id="team_nba_min", name="Minnesota Timberwolves", abbreviations=("MIN",), aliases=("timberwolves", "wolves"), location="Minnesota"),
    _nba(team_id="team_nba_nop", name="New Orleans Pelicans", abbreviations=("NOP", "NO"), aliases=("pelicans",), location="New Orleans"),
    _nba(team_id="team_nba_nyk", name="New York Knicks", abbreviations=("NYK", "NY"), aliases=("knicks",), location="New York"),
    _nba(team_id="team_nba_okc", name="Oklahoma City Thunder", abbreviations=("OKC",), aliases=("thunder",), location="Oklahoma City"),
    _nba(team_id="team_nba_orl", name="Orlando Magic", abbreviations=("ORL",), aliases=("magic",), location="Orlando"),
    _nba(team_id="team_nba_phi", name="Philadelphia 76ers", abbreviations=("PHI",), aliases=("76ers", "sixers"), location="Philadelphia"),
    _nba(team_id="team_nba_phx", name="Phoenix Suns", abbreviations=("PHX", "PHO"), aliases=("suns",), location="Phoenix"),
    _nba(team_id="team_nba_por", name="Portland Trail Blazers", abbreviations=("POR",), aliases=("trail blazers", "blazers"), location="Portland"),
    _nba(team_id="team_nba_sac", name="Sacramento Kings", abbreviations=("SAC",), aliases=("kings",), location="Sacramento"),
    _nba(team_id="team_nba_sas", name="San Antonio Spurs", abbreviations=("SAS", "SA"), aliases=("spurs",), location="San Antonio"),
    _nba(team_id="team_nba_tor", name="Toronto Raptors", abbreviations=("TOR",), aliases=("raptors",), location="Toronto"),
    _nba(team_id="team_nba_uta", name="Utah Jazz", abbreviations=("UTA", "UTAH"), aliases=("jazz",), location="Utah"),
    _nba(team_id="team_nba_was", name="Washington Wizards", abbreviations=("WAS", "WSH"), aliases=("wizards",), location="Washington"),
)

LOCAL_PRIORITY_TEAM_IDS = frozenset(
    spec.team_id for spec in PRO_TEAMS if spec.market == "kansas_city"
)
DEFAULT_FOLLOW_TEAM_IDS = tuple(
    spec.team_id for spec in PRO_TEAMS if spec.market == "kansas_city"
)

_BY_ID = {spec.team_id: spec for spec in PRO_TEAMS}


def team_by_id(team_id: str) -> ProTeam | None:
    return _BY_ID.get(team_id)


def teams_for_league(league: str) -> tuple[ProTeam, ...]:
    return tuple(spec for spec in PRO_TEAMS if spec.league == league)


def default_provider_ids() -> dict[str, str]:
    """Hard-wired BALLDONTLIE team IDs for KC defaults. Not streaming rights."""
    return {
        spec.team_id: spec.provider_team_id
        for spec in PRO_TEAMS
        if spec.provider_team_id
    }


def match_provider_team(league: str, provider_team: dict | None) -> ProTeam | None:
    """Map a BALLDONTLIE team object onto the Three-Zone catalog, or None."""
    if not isinstance(provider_team, dict):
        return None
    candidates = teams_for_league(league)
    raw_id = provider_team.get("id")
    if raw_id is not None:
        pid = str(raw_id)
        for spec in candidates:
            if spec.provider_team_id and spec.provider_team_id == pid:
                return spec
    abbr = str(provider_team.get("abbreviation") or "").strip().upper()
    full = " ".join(
        str(provider_team.get(key) or "")
        for key in ("full_name", "display_name", "short_display_name", "name", "location")
    ).strip().lower()
    name = str(provider_team.get("name") or "").strip().lower()
    location = str(provider_team.get("location") or "").strip().lower()
    display = str(
        provider_team.get("full_name")
        or provider_team.get("display_name")
        or ""
    ).strip().lower()

    for spec in candidates:
        spec_name = spec.name.lower()
        if display and display == spec_name:
            return spec
        if full and spec_name in full:
            return spec
    for spec in candidates:
        if abbr and abbr in spec.abbreviations:
            loc = spec.location.lower()
            if loc and location and loc not in location and loc not in full:
                continue
            if name and name in spec.name.lower():
                return spec
            if display and spec.name.lower() == display:
                return spec
            if name and name in spec.aliases:
                return spec
            continue
    for spec in candidates:
        for alias in spec.aliases:
            if alias == name or (alias in full if alias else False):
                if len(alias) < 5 and alias != name:
                    continue
                return spec
    return None


def catalog_public() -> list[dict]:
    """Secret-free catalog rows for API/ops surfaces."""
    rows = []
    for spec in PRO_TEAMS:
        rows.append({
            "team_id": spec.team_id,
            "league": spec.league,
            "name": spec.name,
            "abbreviation": spec.abbreviations[0] if spec.abbreviations else None,
            "market": spec.market,
            "priority": spec.priority,
            "sport": spec.sport,
            "level": spec.level,
        })
    return rows
