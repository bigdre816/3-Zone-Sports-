"""Unified member identity for Bearer sessions and the member cookie.

Login and register already issue both credentials. Every member, catalog, and
network route must resolve them to the same ``users`` row. Social APIs must not
introduce a third session type.
"""

from __future__ import annotations

from .control_plane import AuthError


def resolve_identity(cp, portal, bearer_token: str | None = None,
                     member_session_id: str | None = None):
    """Return the ``users`` dict for a Bearer token or ``tz_member_session``.

    Bearer is preferred when both are present so API clients and the member
    site share one identity. A missing or unusable credential raises
    ``AuthError`` only when the caller required a session; pass
    ``required=False`` via :func:`resolve_identity_optional`.
    """
    token = (bearer_token or "").strip()
    if token:
        return cp.verify_session(token)
    sid = (member_session_id or "").strip()
    if sid:
        _row, user = portal.session(sid)
        return user
    raise AuthError("authentication required", "missing_session")


def resolve_identity_optional(cp, portal, bearer_token: str | None = None,
                              member_session_id: str | None = None):
    """Like :func:`resolve_identity` but returns ``None`` when unsigned."""
    token = (bearer_token or "").strip()
    sid = (member_session_id or "").strip()
    if not token and not sid:
        return None
    try:
        return resolve_identity(cp, portal, token, sid)
    except AuthError:
        return None


def bearer_from_header(authorization: str | None) -> str | None:
    raw = authorization or ""
    if raw.startswith("Bearer "):
        return raw[len("Bearer "):].strip() or None
    return None
