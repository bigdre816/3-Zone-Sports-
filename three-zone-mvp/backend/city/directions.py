"""External maps directions URL helper.

Builds a Google Maps directions deep link. Opening this URL is not native
navigation and MUST NOT emit navigation.started or navigation.arrived.
"""

from __future__ import annotations

from urllib.parse import urlencode


def external_directions_url(
    *,
    dest_lat: float,
    dest_lng: float,
    dest_name: str | None = None,
    origin_lat: float | None = None,
    origin_lng: float | None = None,
) -> str:
    # Coordinate destination is stable; name is display-only and unused here so
    # a renamed venue cannot send the member to the wrong pin.
    _ = dest_name
    params = {
        "api": "1",
        "destination": f"{dest_lat:.6f},{dest_lng:.6f}",
        "travelmode": "driving",
    }
    if origin_lat is not None and origin_lng is not None:
        params["origin"] = f"{origin_lat:.6f},{origin_lng:.6f}"
    return "https://www.google.com/maps/dir/?" + urlencode(params)
