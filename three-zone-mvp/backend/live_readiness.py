#!/usr/bin/env python3
"""Print live-publication readiness for the current environment.

Does not print secret values. Exit 0 when the selected media rail can start;
exit 1 when blockers remain. Demo rail is always ready for local publish drills.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config  # noqa: E402


def _probe_cloudflare_token(token: str) -> dict:
    if not token:
        return {"ok": False, "reason": "missing_token"}
    import json as _json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/user/tokens/verify",
        headers={"Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = _json.loads(resp.read().decode())
        status = (body.get("result") or {}).get("status")
        return {"ok": bool(body.get("success") and status == "active"), "status": status}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"http_{exc.code}"}
    except Exception:
        return {"ok": False, "reason": "unreachable"}


def readiness(cfg: Config) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    checks: dict = {
        "env": cfg.env,
        "media_provider": cfg.media_provider,
        "public_base_url_set": bool(cfg.public_base_url),
        "allowed_origins": len(cfg.allowed_origins),
        "wildcard_origins": "*" in cfg.allowed_origins or "*" in cfg.cf_allowed_origins,
        "token_secret_is_demo": cfg.token_secret.startswith("three-zone-demo-"),
        "media_key_is_demo": cfg.media_service_key.startswith("three-zone-demo-"),
        "xrpl_mode": cfg.xrpl_mode,
    }

    if checks["wildcard_origins"]:
        blockers.append("wildcard origins are set; use exact playback origins")

    if cfg.media_provider == "demo":
        checks["demo_rail"] = "ready"
        warnings.append("demo rail only — OBS/Cloudflare Stream ingest is not active")
    elif cfg.media_provider == "cloudflare":
        missing = []
        if not cfg.cf_account_id:
            missing.append("TZ_CLOUDFLARE_ACCOUNT_ID")
        if not cfg.cf_api_token:
            missing.append("TZ_CLOUDFLARE_API_TOKEN or CLOUDFLARE")
        if not cfg.cf_customer_code:
            missing.append("TZ_CLOUDFLARE_CUSTOMER_CODE")
        if not cfg.cf_webhook_secret:
            missing.append("TZ_CLOUDFLARE_WEBHOOK_SECRET")
        checks["cloudflare_fields_present"] = not missing
        if missing:
            blockers.extend(f"missing {name}" for name in missing)
        probe = _probe_cloudflare_token(cfg.cf_api_token)
        checks["cloudflare_token_probe"] = probe
        if not probe.get("ok"):
            blockers.append("CLOUDFLARE API token is missing or invalid")
        if not cfg.public_base_url.startswith("https://") and cfg.is_production:
            blockers.append("TZ_PUBLIC_BASE_URL must be https in production for webhooks")
    else:
        blockers.append(f"unknown media provider: {cfg.media_provider}")

    if cfg.is_production:
        if checks["token_secret_is_demo"] or checks["media_key_is_demo"]:
            blockers.append("production still has demo token secrets")
        for account, password in cfg.seed_passwords.items():
            if password.startswith("change-me-"):
                blockers.append(f"seed password for {account} is still the demo value")

    if cfg.xrpl_mode in ("testnet", "mainnet"):
        if not all((cfg.xrpl_rpc_url, cfg.xrpl_audit_account, cfg.xrpl_signing_secret)):
            blockers.append("live XRPL mode is missing signing configuration")
    else:
        warnings.append("XRPL settlement receipts are demo/simulated")

    ready = not blockers
    return {
        "ready_to_publish_live": ready,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }


def main() -> int:
    try:
        cfg = Config.from_env()
    except RuntimeError as exc:
        report = {
            "ready_to_publish_live": False,
            "checks": {"env": os.environ.get("TZ_ENV", "development")},
            "blockers": [str(exc)],
            "warnings": [],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    report = readiness(cfg)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready_to_publish_live"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
