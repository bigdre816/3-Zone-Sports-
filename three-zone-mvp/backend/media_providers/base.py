"""Hosted media provider contract. Cloudflare is the first real rail; demo is tests/local."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ProvisionResult:
    input_id: str
    ingest_url: str
    stream_key: str
    state: str
    recording_policy: dict


@dataclass
class ProviderStatus:
    state: str
    active_video_id: str | None = None
    replay_video_id: str | None = None
    recording_state: str | None = None
    error: str | None = None
    connected: bool = False


@dataclass
class WebhookEvent:
    input_id: str
    event_type: str
    timestamp: str
    error: str | None = None
    video_id: str | None = None


@dataclass
class AnalyticsSnapshot:
    video_id: str | None
    minutes_viewed: float | None
    window_start: float | None
    window_end: float | None
    available: bool
    raw_summary: dict


class MediaProvider(Protocol):
    name: str

    def provision(self, event: dict) -> ProvisionResult: ...
    def rotate_key(self, event: dict) -> ProvisionResult: ...
    def status(self, event: dict) -> ProviderStatus: ...
    def playback_url(self, event: dict, expires_at: float) -> tuple[str, str]: ...
    def disable(self, event: dict) -> ProviderStatus: ...
    def parse_webhook(self, payload: dict) -> WebhookEvent: ...
    def fetch_analytics(self, event: dict) -> AnalyticsSnapshot: ...
