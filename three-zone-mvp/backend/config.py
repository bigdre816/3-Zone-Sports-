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
DEMO_SEED_PASSWORDS = {
    "demo-viewer": "change-me-viewer-local",
    "demo-worker": "change-me-worker-local",
    "demo-owner": "change-me-owner-local",
}

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
    xrpl_rpc_url: str = ""
    xrpl_network: str = ""
    xrpl_audit_account: str = ""
    xrpl_signing_secret: str = ""
    xrpl_key_id: str = ""
    seed_passwords: dict = field(default_factory=dict)
    media_provider: str = "fake"
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_webhook_secret: str = ""
    max_post_video_seconds: int = 90
    max_game_clip_seconds: int = 90
    max_game_bytes: int = 8 * 1024 * 1024 * 1024
    max_photo_bytes: int = 8 * 1024 * 1024
    public_app_url: str = ""
    fake_webhook_secret: str = "fake-webhook-secret"

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
            xrpl_rpc_url=os.environ.get("XRPL_RPC_URL", ""),
            xrpl_network=os.environ.get("XRPL_NETWORK", ""),
            xrpl_audit_account=os.environ.get("XRPL_AUDIT_ACCOUNT", ""),
            xrpl_signing_secret=os.environ.get("XRPL_SIGNING_SECRET", ""),
            xrpl_key_id=os.environ.get("XRPL_KEY_ID", ""),
            seed_passwords={
                "demo-viewer": os.environ.get("TZ_SEED_PASSWORD_VIEWER", DEMO_SEED_PASSWORDS["demo-viewer"]),
                "demo-worker": os.environ.get("TZ_SEED_PASSWORD_WORKER", DEMO_SEED_PASSWORDS["demo-worker"]),
                "demo-owner": os.environ.get("TZ_SEED_PASSWORD_OWNER", DEMO_SEED_PASSWORDS["demo-owner"]),
            },
            media_provider=os.environ.get("TZ_MEDIA_PROVIDER", "fake").strip().lower(),
            cloudflare_account_id=os.environ.get("TZ_CLOUDFLARE_ACCOUNT_ID", ""),
            cloudflare_api_token=os.environ.get("TZ_CLOUDFLARE_API_TOKEN", ""),
            cloudflare_webhook_secret=os.environ.get("TZ_CLOUDFLARE_WEBHOOK_SECRET", ""),
            max_post_video_seconds=int(os.environ.get("TZ_MAX_POST_VIDEO_SECONDS", "90")),
            max_game_clip_seconds=int(os.environ.get("TZ_MAX_GAME_CLIP_SECONDS", "90")),
            max_game_bytes=int(os.environ.get("TZ_MAX_GAME_BYTES", str(8 * 1024 * 1024 * 1024))),
            max_photo_bytes=int(os.environ.get("TZ_MAX_PHOTO_BYTES", str(8 * 1024 * 1024))),
            public_app_url=os.environ.get("TZ_PUBLIC_APP_URL", ""),
            fake_webhook_secret=os.environ.get("TZ_FAKE_WEBHOOK_SECRET", "fake-webhook-secret"),
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
        if not all((self.xrpl_rpc_url, self.xrpl_network, self.xrpl_audit_account,
                    self.xrpl_signing_secret, self.xrpl_key_id)):
            problems.append("XRPL configuration must be complete")
        for account, password in self.seed_passwords.items():
            if password == DEMO_SEED_PASSWORDS.get(account):
                problems.append(f"TZ_SEED_PASSWORD for {account} is still the demo value")
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
            "zones": ["midwest", "west", "east"],
            "simulation": self.env in ("demo", "development", "local"),
            "register_enabled": True,
            "media_provider": self.media_provider,
            "max_post_video_seconds": self.max_post_video_seconds,
            "max_game_clip_seconds": self.max_game_clip_seconds,
            "sports": ["basketball", "football", "soccer", "baseball", "volleyball", "other"],
            "feed_ranking": "published_at DESC, post_id DESC (chronological; not machine learning)",
        }
