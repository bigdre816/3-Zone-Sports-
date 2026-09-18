#!/usr/bin/env python3
"""Check that app.3zonesports.com is the live Lovable member host.

Plane: Runtime + public catalog. This does not change DNS; it reads public
records so a NXDOMAIN report can be distinguished from a cached miss, a
Cloudflare bot block, or a Lovable badge leak.

DNS for 3zonesports.com is IONOS (ui-dns), not a Cloudflare zone. Lovable's
edge answers HTTPS with ``server: cloudflare``.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlparse


MEMBER_HOST = "app.3zonesports.com"
MEMBER_ORIGIN = "https://app.3zonesports.com"
LOVABLE_EDGE_A = "185.158.133.1"
VERIFY_TXT_HOST = "_lovable.app.3zonesports.com"
VERIFY_TXT_PREFIX = "lovable_verify="
API_ORIGIN = "https://three-zone-sports-1.onrender.com"
PUBLIC_ORIGIN = "https://3zonesports.com"
GITHUB_PAGES_A = {
    "185.199.108.153",
    "185.199.109.153",
    "185.199.110.153",
    "185.199.111.153",
}
RENDER_INGRESS_A = "216.24.57.1"
DOH = {
    "google": "https://dns.google/resolve?name={name}&type={rrtype}",
    "cloudflare": "https://cloudflare-dns.com/dns-query?name={name}&type={rrtype}",
}
BROWSER_UA = (
    "Mozilla/5.0 (compatible; ThreeZoneHostnameCheck/1.0; +https://3zonesports.com/)"
)
REDIRECT_CODES = {301, 302, 303, 307, 308}
LOVABLE_ALIAS = "https://threezonesport.lovable.app"


def _doh(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/dns-json", "User-Agent": BROWSER_UA},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lookup(name: str, rrtype: str = "A") -> dict[str, list[str]]:
    answers: dict[str, list[str]] = {}
    for label, template in DOH.items():
        payload = _doh(template.format(name=name, rrtype=rrtype))
        records = [item["data"] for item in payload.get("Answer") or [] if "data" in item]
        answers[label] = records
    return answers


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep 3xx responses so a bounce off the member host cannot look like 200."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener() -> urllib.request.OpenerDirector:
    https = urllib.request.HTTPSHandler(context=ssl.create_default_context())
    return urllib.request.build_opener(https, NoRedirectHandler)


def _header(headers: dict[str, str], name: str) -> str:
    lower = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower:
            return str(value).strip()
    return ""


def _origin(url: str | None) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _redirect_origin(location: str | None, request_url: str) -> str:
    """Origin a browser would use for Location, including relative hops."""
    raw = (location or "").strip()
    if not raw:
        return ""
    return _origin(urljoin(request_url, raw))


def _request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None):
    req = urllib.request.Request(
        url,
        method=method,
        headers={"User-Agent": BROWSER_UA, **(headers or {})},
    )
    try:
        with _opener().open(req, timeout=20) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def evaluate(
    lookups: dict[str, dict[str, list[str]]],
    https_status: int,
    acao: str | None,
    *,
    member_location: str | None = None,
    alias_status: int | None = None,
    alias_location: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return (failures, warnings). Empty failures means the app hostname is live.

    Redirects are not followed. A 302 off ``app.3zonesports.com`` is a failure,
    even if the hop would have landed on 200. The Lovable alias must 3xx to the
    first-party member origin; a 200 on ``lovable.app`` is not live-on-app.
    """
    failures: list[str] = []
    warnings: list[str] = []
    a_records = lookups["app_a"]
    for resolver, records in a_records.items():
        if LOVABLE_EDGE_A not in records:
            failures.append(
                f"{resolver} A for {MEMBER_HOST} is {records or ['(none)']}, expected {LOVABLE_EDGE_A}"
            )
    txt_records = lookups.get("verify_txt") or {}
    for resolver, records in txt_records.items():
        values = [item.strip('"') for item in records]
        if not any(item.startswith(VERIFY_TXT_PREFIX) for item in values):
            failures.append(
                f"{resolver} TXT for {VERIFY_TXT_HOST} is {values or ['(none)']}, expected {VERIFY_TXT_PREFIX}…"
            )
    apex = lookups.get("apex_a") or {}
    for resolver, records in apex.items():
        if RENDER_INGRESS_A in records:
            warnings.append(
                f"{resolver} apex A includes Render ingress {RENDER_INGRESS_A}; "
                f"keep only GitHub Pages {sorted(GITHUB_PAGES_A)}"
            )
    aaaa = lookups.get("app_aaaa") or {}
    if aaaa and not any(aaaa.values()):
        warnings.append("no AAAA for app.3zonesports.com; IPv4-only is expected")
    member_loc = (member_location or "").strip() or None
    if https_status in REDIRECT_CODES:
        loc_origin = _redirect_origin(member_loc, MEMBER_ORIGIN + "/")
        if loc_origin != MEMBER_ORIGIN:
            failures.append(
                f"GET {MEMBER_ORIGIN}/ returned HTTP {https_status} to {member_loc!r}; "
                f"expected 200 on {MEMBER_ORIGIN} without leaving the host"
            )
    elif https_status != 200:
        failures.append(f"GET {MEMBER_ORIGIN}/ returned HTTP {https_status}, expected 200")
    if acao != MEMBER_ORIGIN:
        failures.append(
            f"API CORS for {MEMBER_ORIGIN} is {acao!r}, expected the member origin"
        )
    if alias_status is not None:
        alias_loc = (alias_location or "").strip() or None
        alias_origin = _redirect_origin(alias_loc, LOVABLE_ALIAS + "/")
        if alias_status not in REDIRECT_CODES or alias_origin != MEMBER_ORIGIN:
            failures.append(
                f"Lovable alias returned HTTP {alias_status} Location {alias_loc!r}; "
                f"expected a redirect to {MEMBER_ORIGIN}"
            )
    return failures, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()

    lookups = {
        "app_a": lookup(MEMBER_HOST, "A"),
        "app_aaaa": lookup(MEMBER_HOST, "AAAA"),
        "verify_txt": lookup(VERIFY_TXT_HOST, "TXT"),
        "apex_a": lookup("3zonesports.com", "A"),
        "ns": lookup("3zonesports.com", "NS"),
    }
    status, headers, body = _request(MEMBER_ORIGIN + "/")
    alias_status, alias_headers, _ = _request(LOVABLE_ALIAS + "/")
    cors_status, cors_headers, _ = _request(
        API_ORIGIN + "/api/health",
        headers={"Origin": MEMBER_ORIGIN},
    )
    member_location = _header(headers, "Location") or None
    alias_location = _header(alias_headers, "Location") or None
    failures, warnings = evaluate(
        lookups,
        https_status=status,
        acao=_header(cors_headers, "Access-Control-Allow-Origin") or None,
        member_location=member_location,
        alias_status=alias_status,
        alias_location=alias_location,
    )
    html = body.decode("utf-8", "replace")
    report = {
        "member_host": MEMBER_HOST,
        "dns_provider": "IONOS (ui-dns nameservers), not Cloudflare DNS",
        "lookups": lookups,
        "https_status": status,
        "https_server": _header(headers, "Server") or None,
        "lovable_alias_status": alias_status,
        "lovable_alias_location": alias_location,
        "member_location": member_location,
        "api_cors_status": cors_status,
        "api_cors_allow_origin": _header(cors_headers, "Access-Control-Allow-Origin") or None,
        "lovable_badge": "lovable-badge" in html,
        "twitter_site_lovable": "@Lovable" in html,
        "public_origin": PUBLIC_ORIGIN,
        "failures": failures,
        "warnings": warnings,
        "ok": not failures,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"DNS host: {report['dns_provider']}")
        print(f"A {MEMBER_HOST}: {lookups['app_a']}")
        print(f"TXT {VERIFY_TXT_HOST}: {lookups['verify_txt']}")
        print(f"HTTPS {MEMBER_ORIGIN}/ → {status} server={report['https_server']}")
        if member_location:
            print(f"member Location: {member_location}")
        print(f"Lovable alias → {alias_status} {report['lovable_alias_location']}")
        print(f"API CORS allow-origin: {report['api_cors_allow_origin']}")
        if report["lovable_badge"]:
            print("note: Lovable 'Made with' badge is still injected on the member HTML")
        if report["twitter_site_lovable"]:
            print("note: twitter:site is still @Lovable on the member HTML")
        for item in warnings:
            print(f"note: {item}")
        if failures:
            print("FAIL")
            for item in failures:
                print(f" - {item}")
        else:
            print("PASS: app.3zonesports.com resolves publicly and is admitted by the API")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
