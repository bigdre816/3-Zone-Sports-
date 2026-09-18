"""BALLDONTLIE live sports feeds — normalized, fail-closed, server-side only.

Score/provider data is not a streaming entitlement, media lease, or LIVE_PUBLIC
grant. College and high-school leagues are not configured on this provider.
"""

from .catalog import LOCAL_PRIORITY_TEAM_IDS, PRO_TEAMS, default_provider_ids, team_by_id
from .service import SportsFeedService, RIGHTS_NOTE, GAPS

__all__ = [
    "SportsFeedService",
    "PRO_TEAMS",
    "LOCAL_PRIORITY_TEAM_IDS",
    "default_provider_ids",
    "team_by_id",
    "RIGHTS_NOTE",
    "GAPS",
]
