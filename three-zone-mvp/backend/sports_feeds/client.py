"""Server-side BALLDONTLIE HTTP client.

Auth is the `Authorization` header with the raw API key (no Bearer prefix),
per current BALLDONTLIE docs. Responses are never logged. Missing keys fail
closed as not_configured — this module is not called in that case.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

DEFAULT_BASE = "https://api.balldontlie.io"
DEFAULT_TIMEOUT = 8.0
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 30.0
USER_AGENT = "three-zone-sports-feeds/1.0"


class FeedClientError(Exception):
    def __init__(self, kind: str, message: str = "", status: int | None = None):
        super().__init__(message or kind)
        self.kind = kind
        self.status = status


class NotConfiguredError(FeedClientError):
    def __init__(self):
        super().__init__("not_configured", "BALLDONTLIE_API_KEY is not set")


def _encode_params(params: dict | None) -> str:
    if not params:
        return ""
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((key, str(item)))
        else:
            pairs.append((key, str(value)))
    return urllib.parse.urlencode(pairs, doseq=True)


class BalldontlieClient:
    """Thin urllib client with timeouts, bounded retries, and 429 Retry-After."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE,
        timeout: float = DEFAULT_TIMEOUT,
        sleeper: Callable[[float], None] | None = None,
        opener=None,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout
        self._sleep = sleeper or time.sleep
        self._opener = opener
        self._nba_prefix: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def get(self, path: str, params: dict | None = None) -> dict:
        if not self.configured:
            raise NotConfiguredError()
        query = _encode_params(params)
        url = self.base_url + path
        if query:
            url = url + "?" + query
        last_error: FeedClientError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._once(url)
            except FeedClientError as exc:
                last_error = exc
                if exc.kind in ("not_configured", "unauthorized", "http_error") and exc.status in (400, 401, 403, 404):
                    raise
                if attempt >= MAX_ATTEMPTS:
                    raise
                delay = 0.4 * (2 ** (attempt - 1))
                if exc.kind == "rate_limited":
                    delay = min(MAX_RETRY_AFTER, float(exc.args[1]) if len(exc.args) > 1 else 2.0)
                self._sleep(delay)
        raise last_error or FeedClientError("unavailable")

    def _once(self, url: str) -> dict:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": self.api_key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        ctx = ssl.create_default_context()
        try:
            if self._opener is not None:
                resp_cm = self._opener(request, timeout=self.timeout)
            else:
                resp_cm = urllib.request.urlopen(request, timeout=self.timeout, context=ctx)
            with resp_cm as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            retry_after = None
            try:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
            except Exception:
                retry_after = None
            # Drain but never retain or log the credentialed body.
            try:
                exc.read()
            except Exception:
                pass
            if exc.code == 429:
                wait = 2.0
                if retry_after:
                    try:
                        wait = min(MAX_RETRY_AFTER, float(retry_after))
                    except ValueError:
                        wait = 2.0
                err = FeedClientError("rate_limited", "provider rate limited", status=429)
                err.args = ("rate_limited", wait)
                raise err from None
            if exc.code in (401, 403):
                raise FeedClientError("unauthorized", "provider rejected credentials", status=exc.code) from None
            if exc.code == 404:
                raise FeedClientError("http_error", "not found", status=404) from None
            raise FeedClientError("http_error", f"http {exc.code}", status=exc.code) from None
        except TimeoutError as exc:
            raise FeedClientError("timeout", "provider timeout") from exc
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc) or exc)
            if "timed out" in reason.lower():
                raise FeedClientError("timeout", "provider timeout") from exc
            raise FeedClientError("network", "provider unreachable") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FeedClientError("parse_error", "invalid provider payload") from exc
        if not isinstance(payload, dict):
            raise FeedClientError("parse_error", "invalid provider payload")
        return payload

    def list_teams(self, league: str) -> list[dict]:
        payload = self._get_league(league, "teams", {"per_page": 100})
        data = payload.get("data")
        return list(data) if isinstance(data, list) else []

    def list_games(self, league: str, *, dates: list[str], team_ids: list[str] | None = None) -> list[dict]:
        params: dict = {"per_page": 100, "dates[]": dates}
        if team_ids:
            params["team_ids[]"] = team_ids
        rows: list[dict] = []
        cursor = None
        pages = 0
        while pages < 4:
            page_params = dict(params)
            if cursor is not None:
                page_params["cursor"] = cursor
            payload = self._get_league(league, "games", page_params)
            data = payload.get("data")
            if isinstance(data, list):
                rows.extend(item for item in data if isinstance(item, dict))
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            cursor = meta.get("next_cursor")
            pages += 1
            if not cursor:
                break
        return rows

    def _get_league(self, league: str, resource: str, params: dict) -> dict:
        last: FeedClientError | None = None
        for path in self._paths(league, resource):
            try:
                payload = self.get(path, params)
            except FeedClientError as exc:
                last = exc
                if exc.status == 404:
                    continue
                raise
            if league == "NBA":
                self._nba_prefix = "/nba/v1" if path.startswith("/nba/") else "/v1"
            return payload
        raise last or FeedClientError("http_error", "not found", status=404)

    def _paths(self, league: str, resource: str) -> list[str]:
        if league != "NBA":
            return [f"/{league.lower()}/v1/{resource}"]
        if self._nba_prefix:
            return [f"{self._nba_prefix}/{resource}"]
        # Current OpenAPI uses /nba/v1; older docs use /v1.
        return [f"/nba/v1/{resource}", f"/v1/{resource}"]
