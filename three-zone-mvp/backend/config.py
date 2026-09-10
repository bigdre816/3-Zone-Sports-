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


def _truthy(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _first_env(*names: str) -> str:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and raw.strip():
            return raw.strip()
    return ""


def _cloudflare_credentials() -> tuple[str, str, str, str]:
    """Load Stream credentials. Cursor environment secrets may use CLOUDFLARE.

    A JSON object in CLOUDFLARE is also accepted so one dashboard secret can
    carry account id, token, customer code, and webhook secret. Never log these.
    """
    import json
    account = _first_env("TZ_CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT_ID")
    token = _first_env("TZ_CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE")
    customer = _first_env("TZ_CLOUDFLARE_CUSTOMER_CODE", "CLOUDFLARE_CUSTOMER_CODE")
    webhook = _first_env("TZ_CLOUDFLARE_WEBHOOK_SECRET", "CLOUDFLARE_WEBHOOK_SECRET")
    blob_raw = _first_env("CLOUDFLARE")
    if blob_raw.startswith("{") and blob_raw.endswith("}"):
        try:
            blob = json.loads(blob_raw)
        except json.JSONDecodeError:
            blob = {}
        if isinstance(blob, dict):
            account = account or str(blob.get("account_id") or blob.get("TZ_CLOUDFLARE_ACCOUNT_ID") or "")
            token = str(
                blob.get("api_token") or blob.get("token") or blob.get("TZ_CLOUDFLARE_API_TOKEN") or token
            )
            customer = customer or str(
                blob.get("customer_code") or blob.get("TZ_CLOUDFLARE_CUSTOMER_CODE") or ""
            )
            webhook = webhook or str(
                blob.get("webhook_secret") or blob.get("TZ_CLOUDFLARE_WEBHOOK_SECRET") or ""
            )
    return account, token, customer, webhook


def cloudflare_live_credentials_complete() -> bool:
    """True when Stream live-rail secrets are all present (values never logged)."""
    account, token, customer, webhook = _cloudflare_credentials()
    return bool(account and token and customer and webhook)


@dataclass
class Config:
    """Resolved configuration for one running instance."""

    env: str = "development"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    ws_host: str = "127.0.0.1"
    ws_port: int = 8765
    database_url: str = ""
    database_path: str = "data/three_zone.sqlite3"
    data_dir: str = "data"
    allowed_origins: list[str] = field(default_factory=list)
    token_secret: str = DEMO_TOKEN_SECRET
    media_service_key: str = DEMO_MEDIA_SERVICE_KEY
    session_ttl: int = 3600
    lease_ttl: int = 60
    ingest_ttl: int = 6 * 3600
    heartbeat_timeout: int = 12
    max_body_bytes: int = 64 * 1024
    webhook_max_body_bytes: int = 512 * 1024
    ws_max_message_bytes: int = 16 * 1024
    ws_max_messages_per_10s: int = 40
    ws_max_conns_per_ip: int = 20
    media_provider: str = "demo"  # live rail: demo | cloudflare (TZ_LIVE_MEDIA_PROVIDER)
    live_media_provider: str = "demo"
    ugc_media_provider: str = "fake"  # member network: fake | cloudflare
    public_base_url: str = ""
    cf_account_id: str = ""
    cf_api_token: str = ""
    cf_customer_code: str = ""
    cf_webhook_secret: str = ""
    cf_allowed_origins: list[str] = field(default_factory=list)
    cf_delete_recording_after_days: int = 365
    cf_prefer_low_latency: bool = False
    viewer_heartbeat_interval: int = 15
    viewer_stale_after: int = 90
    xrpl_mode: str = "demo"
    xrpl_rpc_url: str = ""
    xrpl_network: str = ""
    xrpl_audit_account: str = ""
    xrpl_signing_secret: str = ""
    xrpl_key_id: str = ""
    xrpl_publication_mode: str = "batch"
    xrpl_batch_max_records: int = 500
    xrpl_batch_max_age_seconds: int = 3600
    seed_passwords: dict = field(default_factory=dict)
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_webhook_secret: str = ""
    max_post_video_seconds: int = 90
    max_game_clip_seconds: int = 90
    max_game_bytes: int = 8 * 1024 * 1024 * 1024
    max_photo_bytes: int = 8 * 1024 * 1024
    public_app_url: str = ""
    fake_webhook_secret: str = "fake-webhook-secret"
    photo_storage: str = "fake"
    photo_s3_endpoint: str = ""
    photo_s3_bucket: str = ""
    photo_s3_access_key: str = ""
    photo_s3_secret_key: str = ""
    photo_s3_region: str = "auto"
    photo_webhook_secret: str = ""
    moten_service_url: str = ""
    moten_shared_secret: str = ""
    moten_timeout_seconds: int = 5

    def __post_init__(self) -> None:
        """Keep live/UGC provider names and Cloudflare credential aliases in sync."""
        name = (self.media_provider or "demo").strip().lower()
        live = (self.live_media_provider or "").strip().lower()
        ugc = (self.ugc_media_provider or "").strip().lower()
        if name == "fake":
            self.live_media_provider = live if live in ("demo", "cloudflare") else "demo"
            self.ugc_media_provider = "fake"
        elif name == "cloudflare":
            self.live_media_provider = "cloudflare"
            self.ugc_media_provider = ugc if ugc in ("fake", "cloudflare") else "cloudflare"
        else:
            self.live_media_provider = live if live in ("demo", "cloudflare") else "demo"
            self.ugc_media_provider = ugc if ugc in ("fake", "cloudflare") else "fake"
        # Events.media_provider is the live rail. Never persist the UGC name.
        self.media_provider = self.live_media_provider
        if not self.cf_account_id and self.cloudflare_account_id:
            self.cf_account_id = self.cloudflare_account_id
        if not self.cf_api_token and self.cloudflare_api_token:
            self.cf_api_token = self.cloudflare_api_token
        if not self.cf_webhook_secret and self.cloudflare_webhook_secret:
            self.cf_webhook_secret = self.cloudflare_webhook_secret
        if not self.cloudflare_account_id:
            self.cloudflare_account_id = self.cf_account_id
        if not self.cloudflare_api_token:
            self.cloudflare_api_token = self.cf_api_token
        if not self.cloudflare_webhook_secret:
            self.cloudflare_webhook_secret = self.cf_webhook_secret

    def live_provider_name(self) -> str:
        return self.live_media_provider if self.live_media_provider in ("demo", "cloudflare") else "demo"

    def ugc_provider_name(self) -> str:
        return self.ugc_media_provider if self.ugc_media_provider in ("fake", "cloudflare") else "fake"

    @classmethod
    def from_env(cls, http_port: int | None = None, ws_port: int | None = None,
                 http_host: str | None = None, ws_host: str | None = None) -> "Config":
        env = os.environ.get("TZ_ENV", "development").strip().lower()
        http_host = http_host or os.environ.get("TZ_HTTP_HOST", "127.0.0.1")
        ws_host = ws_host or os.environ.get("TZ_WS_HOST", "127.0.0.1")
        http_port = int(
            http_port
            or os.environ.get("TZ_HTTP_PORT")
            or os.environ.get("PORT")
            or "8000"
        )
        ws_port = int(ws_port or os.environ.get("TZ_WS_PORT", "8765"))
        default_origin = f"http://127.0.0.1:{http_port}" if http_host in ("0.0.0.0", "::") else f"http://{http_host}:{http_port}"
        allowed = _split_origins(os.environ.get("TZ_ALLOWED_ORIGINS", default_origin))
        if http_host in ("0.0.0.0", "::"):
            for extra in (f"http://127.0.0.1:{http_port}", f"http://localhost:{http_port}"):
                if extra not in allowed:
                    allowed.append(extra)
        cf_origins = _split_origins(os.environ.get("TZ_CLOUDFLARE_ALLOWED_ORIGINS", ",".join(allowed)))
        lease_raw = os.environ.get("TZ_PLAYBACK_LEASE_SECONDS") or os.environ.get("TZ_LEASE_TTL") or "60"
        xrpl_account = os.environ.get("TZ_XRPL_ACCOUNT") or os.environ.get("XRPL_AUDIT_ACCOUNT", "")
        xrpl_secret = os.environ.get("TZ_XRPL_SIGNING_SECRET") or os.environ.get("XRPL_SIGNING_SECRET", "")
        xrpl_rpc = os.environ.get("TZ_XRPL_RPC_URL") or os.environ.get("XRPL_RPC_URL", "")
        cf_account, cf_token, cf_customer, cf_webhook = _cloudflare_credentials()
        legacy = os.environ.get("TZ_MEDIA_PROVIDER", "").strip().lower()
        live_name = os.environ.get("TZ_LIVE_MEDIA_PROVIDER", "").strip().lower()
        ugc_name = os.environ.get("TZ_UGC_MEDIA_PROVIDER", "").strip().lower()
        if not live_name:
            live_name = "cloudflare" if legacy == "cloudflare" else "demo"
        if not ugc_name:
            ugc_name = "cloudflare" if legacy == "cloudflare" else "fake"
        media_provider = live_name
        cfg = cls(
            env=env,
            http_host=http_host,
            http_port=http_port,
            ws_host=ws_host,
            ws_port=ws_port,
            database_url=os.environ.get("TZ_DATABASE_URL", "").strip(),
            database_path=os.environ.get("TZ_DATABASE_PATH", "data/three_zone.sqlite3"),
            data_dir=os.environ.get("TZ_DATA_DIR", "data"),
            allowed_origins=allowed,
            token_secret=os.environ.get("TZ_TOKEN_SECRET", DEMO_TOKEN_SECRET),
            media_service_key=os.environ.get("TZ_MEDIA_SERVICE_KEY", DEMO_MEDIA_SERVICE_KEY),
            session_ttl=int(os.environ.get("TZ_SESSION_TTL", "3600")),
            lease_ttl=int(lease_raw),
            ingest_ttl=int(os.environ.get("TZ_INGEST_TTL", str(6 * 3600))),
            heartbeat_timeout=int(os.environ.get("TZ_HEARTBEAT_TIMEOUT", "12")),
            media_provider=media_provider,
            live_media_provider=live_name,
            ugc_media_provider=ugc_name,
            public_base_url=os.environ.get("TZ_PUBLIC_BASE_URL", default_origin).rstrip("/"),
            cf_account_id=cf_account,
            cf_api_token=cf_token,
            cf_customer_code=cf_customer,
            cf_webhook_secret=cf_webhook,
            cf_allowed_origins=cf_origins,
            cf_delete_recording_after_days=int(os.environ.get("TZ_CLOUDFLARE_DELETE_RECORDING_AFTER_DAYS", "365")),
            cf_prefer_low_latency=_truthy(os.environ.get("TZ_CLOUDFLARE_PREFER_LOW_LATENCY"), False),
            viewer_heartbeat_interval=int(os.environ.get("TZ_VIEWER_HEARTBEAT_INTERVAL_SECONDS", "15")),
            viewer_stale_after=int(os.environ.get("TZ_VIEWER_STALE_AFTER_SECONDS", "90")),
            xrpl_mode=os.environ.get("TZ_XRPL_MODE", "demo").strip().lower() or "demo",
            xrpl_rpc_url=xrpl_rpc,
            xrpl_network=os.environ.get("XRPL_NETWORK", os.environ.get("TZ_XRPL_MODE", "")),
            xrpl_audit_account=xrpl_account,
            xrpl_signing_secret=xrpl_secret,
            xrpl_key_id=os.environ.get("XRPL_KEY_ID", ""),
            xrpl_publication_mode=os.environ.get("TZ_XRPL_PUBLICATION_MODE", "batch").strip().lower() or "batch",
            xrpl_batch_max_records=int(os.environ.get("TZ_XRPL_BATCH_MAX_RECORDS", "500")),
            xrpl_batch_max_age_seconds=int(os.environ.get("TZ_XRPL_BATCH_MAX_AGE_SECONDS", "3600")),
            seed_passwords={
                "demo-viewer": os.environ.get("TZ_SEED_PASSWORD_VIEWER", DEMO_SEED_PASSWORDS["demo-viewer"]),
                "demo-worker": os.environ.get("TZ_SEED_PASSWORD_WORKER", DEMO_SEED_PASSWORDS["demo-worker"]),
                "demo-owner": os.environ.get("TZ_SEED_PASSWORD_OWNER", DEMO_SEED_PASSWORDS["demo-owner"]),
            },
            cloudflare_account_id=cf_account,
            cloudflare_api_token=cf_token,
            cloudflare_webhook_secret=cf_webhook,
            max_post_video_seconds=int(os.environ.get("TZ_MAX_POST_VIDEO_SECONDS", "90")),
            max_game_clip_seconds=int(os.environ.get("TZ_MAX_GAME_CLIP_SECONDS", "90")),
            max_game_bytes=int(os.environ.get("TZ_MAX_GAME_BYTES", str(8 * 1024 * 1024 * 1024))),
            max_photo_bytes=int(os.environ.get("TZ_MAX_PHOTO_BYTES", str(8 * 1024 * 1024))),
            public_app_url=os.environ.get("TZ_PUBLIC_APP_URL", ""),
            fake_webhook_secret=os.environ.get("TZ_FAKE_WEBHOOK_SECRET", "fake-webhook-secret"),
            photo_storage=os.environ.get("TZ_PHOTO_STORAGE", "fake").strip().lower(),
            photo_s3_endpoint=os.environ.get("TZ_PHOTO_S3_ENDPOINT", ""),
            photo_s3_bucket=os.environ.get("TZ_PHOTO_S3_BUCKET", ""),
            photo_s3_access_key=os.environ.get("TZ_PHOTO_S3_ACCESS_KEY", ""),
            photo_s3_secret_key=os.environ.get("TZ_PHOTO_S3_SECRET_KEY", ""),
            photo_s3_region=os.environ.get("TZ_PHOTO_S3_REGION", "auto"),
            photo_webhook_secret=os.environ.get("TZ_PHOTO_WEBHOOK_SECRET", ""),
            moten_service_url=os.environ.get("TZ_MOTEN_SERVICE_URL", "").rstrip("/"),
            moten_shared_secret=os.environ.get("TZ_MOTEN_SHARED_SECRET", ""),
            moten_timeout_seconds=int(os.environ.get("TZ_MOTEN_TIMEOUT_SECONDS", "5")),
        )
        cfg.validate()
        return cfg

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cloudflare_playback_host(self) -> str | None:
        if not self.cf_customer_code:
            return None
        return f"https://customer-{self.cf_customer_code}.cloudflarestream.com"

    @property
    def database_locator(self) -> str:
        return self.database_url or self.database_path

    @property
    def moten_enabled(self) -> bool:
        return bool(self.moten_service_url)

    def validate(self) -> None:
        """Refuse to run in production with demo/weak secrets."""
        live = self.live_provider_name()
        ugc = self.ugc_provider_name()
        if live not in ("demo", "cloudflare"):
            raise RuntimeError("TZ_LIVE_MEDIA_PROVIDER must be demo or cloudflare")
        if ugc not in ("fake", "cloudflare"):
            raise RuntimeError("TZ_UGC_MEDIA_PROVIDER must be fake or cloudflare")
        if self.lease_ttl > 60:
            self.lease_ttl = 60
        if "*" in self.cf_allowed_origins and (self.is_production or live == "cloudflare"):
            if self.is_production:
                raise RuntimeError("TZ_CLOUDFLARE_ALLOWED_ORIGINS must not use a wildcard in production")
        if not self.is_production:
            if live == "cloudflare" or ugc == "cloudflare":
                missing = []
                if not self.cf_account_id:
                    missing.append("TZ_CLOUDFLARE_ACCOUNT_ID")
                if not self.cf_api_token:
                    missing.append("TZ_CLOUDFLARE_API_TOKEN")
                if live == "cloudflare" and not self.cf_customer_code:
                    missing.append("TZ_CLOUDFLARE_CUSTOMER_CODE")
                if not self.cf_webhook_secret:
                    missing.append("TZ_CLOUDFLARE_WEBHOOK_SECRET")
                if missing:
                    raise RuntimeError(
                        "Cloudflare media provider selected but configuration is incomplete: "
                        + ", ".join(missing)
                    )
            if self.xrpl_mode in ("testnet", "mainnet"):
                if not all((self.xrpl_rpc_url, self.xrpl_audit_account, self.xrpl_signing_secret)):
                    raise RuntimeError(
                        "Live XRPL mode requires TZ_XRPL_RPC_URL, TZ_XRPL_ACCOUNT, and TZ_XRPL_SIGNING_SECRET"
                    )
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
        if not (self.database_url or self.database_path):
            problems.append("TZ_DATABASE_URL or TZ_DATABASE_PATH must be set")
        if self.moten_enabled and not self.moten_shared_secret:
            problems.append("TZ_MOTEN_SHARED_SECRET is required when TZ_MOTEN_SERVICE_URL is set")
        if "*" in self.allowed_origins or "*" in self.cf_allowed_origins:
            problems.append("wildcard origins are refused in production")
        if live == "cloudflare" or ugc == "cloudflare":
            if not self.cf_account_id:
                problems.append("TZ_CLOUDFLARE_ACCOUNT_ID is required")
            if not self.cf_api_token:
                problems.append("TZ_CLOUDFLARE_API_TOKEN is required")
            if live == "cloudflare" and not self.cf_customer_code:
                problems.append("TZ_CLOUDFLARE_CUSTOMER_CODE is required")
            if not self.cf_webhook_secret:
                problems.append("TZ_CLOUDFLARE_WEBHOOK_SECRET is required")
        if self.xrpl_mode in ("testnet", "mainnet"):
            if not all((self.xrpl_rpc_url, self.xrpl_audit_account, self.xrpl_signing_secret)):
                problems.append("live XRPL mode is missing signing configuration")
        elif self.xrpl_mode == "demo":
            pass
        else:
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
        host = self.cloudflare_playback_host
        return {
            "env": self.env,
            "ws_url_base": f"ws://{self.ws_host}:{self.ws_port}/ws/events/",
            "session_ttl": self.session_ttl,
            "lease_ttl": self.lease_ttl,
            "heartbeat_timeout": self.heartbeat_timeout,
            "zones": ["midwest", "west", "east"],
            "simulation": self.env in ("demo", "development", "local"),
            "register_enabled": True,
            "media_provider": self.live_provider_name(),
            "live_media_provider": self.live_provider_name(),
            "ugc_media_provider": self.ugc_provider_name(),
            "viewer_heartbeat_interval": self.viewer_heartbeat_interval,
            "hls_enabled": self.live_provider_name() == "cloudflare",
            "cloudflare_playback_host": host,
            "photo_storage": self.photo_storage,
            "max_post_video_seconds": self.max_post_video_seconds,
            "max_game_clip_seconds": self.max_game_clip_seconds,
            "sports": ["basketball", "football", "soccer", "baseball", "volleyball", "other"],
            "feed_ranking": "published_at DESC, post_id DESC (chronological; not machine learning)",
        }
