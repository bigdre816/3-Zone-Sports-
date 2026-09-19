"""Pure departure math for Getting There planning allowances.

Formula (Milestone A fixture):
    suggested_departure = desired_arrival − parking_or_walk − drive_duration
    desired_arrival     = event_time − desired_arrival_offset

    4:00 PM event − 10 min early − 10 min parking − 25 min drive = 3:15 PM

Offsets are planning allowances, not promises of parking availability or
gate time. This module never talks to a traffic provider.
"""

from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT_DESIRED_ARRIVAL_OFFSET_MINUTES = 10
DEFAULT_PARKING_OR_WALK_MINUTES = 10
MAX_ALLOWANCE_MINUTES = 120


def clamp_allowance_minutes(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("allowance minutes must be an integer") from exc
    if minutes < 0 or minutes > MAX_ALLOWANCE_MINUTES:
        raise ValueError(f"allowance minutes must be between 0 and {MAX_ALLOWANCE_MINUTES}")
    return minutes


def desired_arrival(event_time: datetime, offset_minutes: int) -> datetime:
    """Event time minus the early-arrival planning allowance."""
    return event_time - timedelta(minutes=int(offset_minutes))


def suggested_departure(
    event_time: datetime,
    *,
    desired_arrival_offset_minutes: int,
    parking_or_walk_minutes: int,
    drive_duration_seconds: int,
) -> datetime:
    """suggested_departure = desired_arrival − parking_or_walk − drive_duration."""
    arrive = desired_arrival(event_time, desired_arrival_offset_minutes)
    return arrive - timedelta(minutes=int(parking_or_walk_minutes)) - timedelta(
        seconds=int(drive_duration_seconds)
    )


def late_by_seconds(likely_arrival: datetime, target: datetime) -> int:
    return int((likely_arrival - target).total_seconds())
