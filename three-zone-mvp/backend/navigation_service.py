"""Provider-neutral native-navigation contract.

Milestone A defines the seam only. No browser event, button tap, or route estimate
is promoted into an SDK navigation outcome. A native adapter must replace the
unavailable implementation during milestone B and map provider callbacks into
this state machine.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class NavigationState(str, Enum):
    NEEDS_ORIGIN = "needs_origin"
    LOCATING = "locating"
    CALCULATING_ROUTE = "calculating_route"
    ROUTE_READY = "route_ready"
    ESTIMATE_STALE = "estimate_stale"
    STARTING_NAVIGATION = "starting_navigation"
    NAVIGATING = "navigating"
    REROUTING = "rerouting"
    INTERRUPTED = "interrupted"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"
    UNAVAILABLE_OR_FAILED = "unavailable_or_failed"
    PERMISSION_DENIED = "permission_denied"


ALLOWED_TRANSITIONS: dict[NavigationState, frozenset[NavigationState]] = {
    NavigationState.NEEDS_ORIGIN: frozenset({NavigationState.LOCATING, NavigationState.CALCULATING_ROUTE}),
    NavigationState.LOCATING: frozenset({NavigationState.CALCULATING_ROUTE, NavigationState.PERMISSION_DENIED, NavigationState.UNAVAILABLE_OR_FAILED}),
    NavigationState.CALCULATING_ROUTE: frozenset({NavigationState.ROUTE_READY, NavigationState.UNAVAILABLE_OR_FAILED}),
    NavigationState.ROUTE_READY: frozenset({NavigationState.CALCULATING_ROUTE, NavigationState.ESTIMATE_STALE, NavigationState.STARTING_NAVIGATION}),
    NavigationState.ESTIMATE_STALE: frozenset({NavigationState.CALCULATING_ROUTE}),
    NavigationState.STARTING_NAVIGATION: frozenset({NavigationState.NAVIGATING, NavigationState.PERMISSION_DENIED, NavigationState.UNAVAILABLE_OR_FAILED}),
    NavigationState.NAVIGATING: frozenset({NavigationState.REROUTING, NavigationState.INTERRUPTED, NavigationState.ARRIVED, NavigationState.CANCELLED, NavigationState.UNAVAILABLE_OR_FAILED}),
    NavigationState.REROUTING: frozenset({NavigationState.NAVIGATING, NavigationState.INTERRUPTED, NavigationState.CANCELLED, NavigationState.UNAVAILABLE_OR_FAILED}),
    NavigationState.INTERRUPTED: frozenset({NavigationState.NAVIGATING, NavigationState.CANCELLED, NavigationState.UNAVAILABLE_OR_FAILED}),
    NavigationState.ARRIVED: frozenset(),
    NavigationState.CANCELLED: frozenset(),
    NavigationState.UNAVAILABLE_OR_FAILED: frozenset(),
    NavigationState.PERMISSION_DENIED: frozenset({NavigationState.NEEDS_ORIGIN, NavigationState.LOCATING}),
}


@dataclass(frozen=True)
class NavigationCapability:
    available: bool
    provider: str | None
    platform: str
    reason: str | None = None


class NavigationService:
    """Interface for an embedded native guidance adapter."""

    def capability(self) -> NavigationCapability:
        raise NotImplementedError

    def start_session(self, *, city_place_id: str, destination: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def stop_session(self, *, reason: str = "user_cancelled") -> None:
        raise NotImplementedError

    def state(self) -> NavigationState:
        raise NotImplementedError

    def subscribe(self, callback: Callable[[NavigationState, dict[str, Any]], None]) -> Callable[[], None]:
        raise NotImplementedError

    def cleanup(self) -> None:
        raise NotImplementedError


class UnavailableNavigationService(NavigationService):
    """Milestone-A implementation: explicitly unavailable, never simulated."""

    def __init__(self, *, platform: str = "web"):
        self._platform = platform
        self._state = NavigationState.UNAVAILABLE_OR_FAILED

    def capability(self) -> NavigationCapability:
        return NavigationCapability(
            available=False,
            provider=None,
            platform=self._platform,
            reason="native_navigation_not_integrated",
        )

    def start_session(self, *, city_place_id: str, destination: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("native_navigation_not_integrated")

    def stop_session(self, *, reason: str = "user_cancelled") -> None:
        return None

    def state(self) -> NavigationState:
        return self._state

    def subscribe(self, callback: Callable[[NavigationState, dict[str, Any]], None]) -> Callable[[], None]:
        return lambda: None

    def cleanup(self) -> None:
        return None


def transition_allowed(current: NavigationState, target: NavigationState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
