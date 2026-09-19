"""City-plane Getting There (Milestone A) — planning only, not native nav.

Sports is one vertical inside City. Capacitor / member UI lives outside this
repo. This package is the Render API contract: places, route planning, signals,
and a NavigationService capability stub for Milestone B.
"""

from .departure import suggested_departure, desired_arrival
from .directions import external_directions_url
from .navigation import NavigationService
from .places import CityPlaceService, KC_SPORTS_ANCHORS
from .route_planning import RoutePlanningService
from .routes_provider import GoogleRoutesProvider, RoutesProviderError
from .signals import (
    CitySignalService,
    SIGNAL_VOCABULARY,
    DIRECTIONS_REQUESTED,
    NAVIGATION_ROUTE_READY,
    NAVIGATION_STARTED,
    NAVIGATION_ARRIVED,
)

__all__ = [
    "CityPlaceService",
    "CitySignalService",
    "GoogleRoutesProvider",
    "KC_SPORTS_ANCHORS",
    "NavigationService",
    "RoutePlanningService",
    "RoutesProviderError",
    "SIGNAL_VOCABULARY",
    "DIRECTIONS_REQUESTED",
    "NAVIGATION_ROUTE_READY",
    "NAVIGATION_STARTED",
    "NAVIGATION_ARRIVED",
    "desired_arrival",
    "external_directions_url",
    "suggested_departure",
]
