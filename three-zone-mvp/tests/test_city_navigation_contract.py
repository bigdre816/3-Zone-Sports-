from backend.city_http import _CITY_ROUTES
from backend.navigation_service import NavigationState, UnavailableNavigationService, transition_allowed


def test_city_member_and_operator_routes_preserve_server_auth_classes():
    by_handler = {handler: auth for _method, _pattern, handler, auth in _CITY_ROUTES}
    assert by_handler["h_city_config"] == "member"
    assert by_handler["h_city_place_get"] == "member"
    assert by_handler["h_city_event_get"] == "member"
    assert by_handler["h_city_getting_there"] == "member"
    assert by_handler["h_city_place_upsert"] == "operator"
    assert by_handler["h_city_event_upsert"] == "operator"


def test_native_navigation_is_explicitly_unavailable_in_milestone_a():
    service = UnavailableNavigationService(platform="web")
    capability = service.capability()
    assert capability.available is False
    assert capability.reason == "native_navigation_not_integrated"
    assert service.state() == NavigationState.UNAVAILABLE_OR_FAILED


def test_navigation_state_machine_does_not_invent_terminal_outcomes():
    assert transition_allowed(NavigationState.ROUTE_READY, NavigationState.STARTING_NAVIGATION)
    assert transition_allowed(NavigationState.STARTING_NAVIGATION, NavigationState.NAVIGATING)
    assert transition_allowed(NavigationState.NAVIGATING, NavigationState.ARRIVED)
    assert transition_allowed(NavigationState.NAVIGATING, NavigationState.CANCELLED)
    assert not transition_allowed(NavigationState.ROUTE_READY, NavigationState.ARRIVED)
    assert not transition_allowed(NavigationState.ARRIVED, NavigationState.CANCELLED)
    assert not transition_allowed(NavigationState.CANCELLED, NavigationState.ARRIVED)
