"""Runtime configuration for the Three-Zone control-plane MVP.

Configuration is read from environment variables so the same code can run as a
local demo or a hardened pilot. The demo defaults are intentionally obvious and
are refused when ``TZ_ENV=production`` so a real deployment cannot accidentally
ship with a known secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Obvious demo values. They are safe for a local pilot only and are rejected in
# production by :meth:`Config.validate`.
DEMO_TOKEN_SECRET = "three-zone-demo-token-secret-CHANGE-ME-0000000000"
DEMO_MEDIA_SERVICE_KEY = "three-zone-demo-media-service-key-CHANGE-ME-000000"

MIN_SECRET_LEN = 32


def _split_origins(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    """Resolved configuration for one running instance."""

    env: str = "development"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    ws_host: str = "127.0.0.1"
    ws_port: int = 8765
    database_path: str = "data/three_zone.sqlite3"
    allowed_origins: list[str] = field(default_factory=list)
    token_secret: str = DEMO_TOKEN_SECRET
    media_service_key: str = DEMO_MEDIA_SERVICE_KEY
    session_ttl: int = 3600
    lease_ttl: int = 90
    ingest_ttl: int = 6 * 3600
    heartbeat_timeout: int = 12
    max_body_bytes: int = 64 * 1024
    ws_max_message_bytes: int = 16 * 1024
    ws_max_messages_per_10s: int = 40
    ws_max_conns_per_ip: int = 20

    @classmethod
    def from_env(cls, http_port: int | None = None, ws_port: int | None = None,
                 http_host: str | None = None, ws_host: str | None = None) -> "Config":
        env = os.environ.get("TZ_ENV", "development").strip().lower()
        http_host = http_host or os.environ.get("TZ_HTTP_HOST", "127.0.0.1")
        ws_host = ws_host or os.environ.get("TZ_WS_HOST", "127.0.0.1")
        http_port = int(http_port or os.environ.get("TZ_HTTP_PORT", "8000"))
        ws_port = int(ws_port or os.environ.get("TZ_WS_PORT", "8765"))
        default_origin = f"http://{http_host}:{http_port}"
        allowed = _split_origins(os.environ.get("TZ_ALLOWED_ORIGINS", default_origin))
        cfg = cls(
            env=env,
            http_host=http_host,
            http_port=http_port,
            ws_host=ws_host,
            ws_port=ws_port,
            database_path=os.environ.get("TZ_DATABASE_PATH", "data/three_zone.sqlite3"),
            allowed_origins=allowed,
            token_secret=os.environ.get("TZ_TOKEN_SECRET", DEMO_TOKEN_SECRET),
            media_service_key=os.environ.get("TZ_MEDIA_SERVICE_KEY", DEMO_MEDIA_SERVICE_KEY),
            session_ttl=int(os.environ.get("TZ_SESSION_TTL", "3600")),
            lease_ttl=int(os.environ.get("TZ_LEASE_TTL", "90")),
            ingest_ttl=int(os.environ.get("TZ_INGEST_TTL", str(6 * 3600))),
            heartbeat_timeout=int(os.environ.get("TZ_HEARTBEAT_TIMEOUT", "12")),
        )
        cfg.validate()
        return cfg

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate(self) -> None:
        """Refuse to run in production with demo/weak secrets."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.token_secret == DEMO_TOKEN_SECRET:
            problems.append("TZ_TOKEN_SECRET is still the demo value")
        if len(self.token_secret) < MIN_SECRET_LEN:
            problems.append(f"TZ_TOKEN_SECRET must be at least {MIN_SECRET_LEN} characters")
        if self.media_service_key == DEMO_MEDIA_SERVICE_KEY:
            problems.append("TZ_MEDIA_SERVICE_KEY is still the demo value")
        if len(self.media_service_key) < MIN_SECRET_LEN:
            problems.append(f"TZ_MEDIA_SERVICE_KEY must be at least {MIN_SECRET_LEN} characters")
        if self.token_secret == self.media_service_key:
            problems.append("TZ_TOKEN_SECRET and TZ_MEDIA_SERVICE_KEY must be different")
        if not self.allowed_origins:
            problems.append("TZ_ALLOWED_ORIGINS must be set")
        if problems:
            raise RuntimeError(
                "Refusing to start in production with an unsafe configuration: "
                + "; ".join(problems)
            )

    def public_config(self) -> dict:
        """Client-visible configuration. Never includes secrets."""
        return {
            "env": self.env,
            "ws_url_base": f"ws://{self.ws_host}:{self.ws_port}/ws/events/",
            "session_ttl": self.session_ttl,
            "lease_ttl": self.lease_ttl,
            "heartbeat_timeout": self.heartbeat_timeout,
            "demo_accounts": ["demo-viewer", "demo-admin"],
            "zones": ["midwest", "west", "east"],
        }
