#!/usr/bin/env bash
# Per-boot Cloud Agent start. Launches whichever product exists in this
# checkout, waits until it is healthy, then returns.
#
#   main / Three-Zone  →  http://127.0.0.1:8000/      (ops: /ops)
#   Moten Phase 1      →  http://127.0.0.1:8100/
#
# Idempotent: skips a server that is already healthy. Does not bind port 8000
# to the leftover Investment Tracker static file (`System` / `.cursor/serve.py`)
# when Three-Zone is present — that collision forced agents onto ad-hoc ports
# like 18002 and then computer-use subagents failed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG="${CLOUD_AGENT_APP_LOG:-/tmp/cloud-agent-apps.log}"
touch "$LOG"

ready() {
  local url="$1"
  curl -sf --max-time 2 "$url" >/dev/null 2>&1
}

wait_for() {
  local url="$1" name="$2"
  local i
  for i in $(seq 1 60); do
    if ready "$url"; then
      echo "cloud-agent-start: ${name} ready at ${url}"
      return 0
    fi
    sleep 0.5
  done
  echo "cloud-agent-start: ${name} failed to become ready at ${url}" >&2
  tail -n 80 "$LOG" >&2 || true
  return 1
}

maybe_export_cloudflare_live_rail() {
  # Opt into Stream only when credentials are complete. Unset provider stays
  # demo so a missing customer code / webhook secret cannot crash boot.
  if [[ -n "${TZ_LIVE_MEDIA_PROVIDER:-}" || -n "${TZ_MEDIA_PROVIDER:-}" ]]; then
    return 0
  fi
  if (
    cd "$ROOT/three-zone-mvp"
    python3 -c "from backend.config import cloudflare_live_credentials_complete; raise SystemExit(0 if cloudflare_live_credentials_complete() else 1)"
  ); then
    export TZ_LIVE_MEDIA_PROVIDER=cloudflare
    export TZ_CLOUDFLARE_ALLOWED_ORIGINS="${TZ_CLOUDFLARE_ALLOWED_ORIGINS:-${TZ_ALLOWED_ORIGINS:-http://127.0.0.1:8000,http://localhost:8000}}"
    echo "cloud-agent-start: Cloudflare live-rail secrets complete; TZ_LIVE_MEDIA_PROVIDER=cloudflare"
  else
    echo "cloud-agent-start: Cloudflare live rail incomplete; demo provider"
  fi
}

three_zone_media_provider() {
  curl -sf --max-time 2 http://127.0.0.1:8000/api/config 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('media_provider',''))" 2>/dev/null || true
}

stop_three_zone() {
  local pid=""
  if [[ -f /tmp/three-zone.pid ]]; then
    pid="$(cat /tmp/three-zone.pid 2>/dev/null || true)"
  fi
  if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    local i
    for i in $(seq 1 30); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
  fi
}

start_three_zone() {
  (
    cd "$ROOT/three-zone-mvp"
    export TZ_HTTP_HOST="${TZ_HTTP_HOST:-0.0.0.0}"
    export TZ_WS_HOST="${TZ_WS_HOST:-0.0.0.0}"
    export TZ_HTTP_PORT="${TZ_HTTP_PORT:-8000}"
    export TZ_WS_PORT="${TZ_WS_PORT:-8765}"
    export TZ_ALLOWED_ORIGINS="${TZ_ALLOWED_ORIGINS:-http://127.0.0.1:8000,http://localhost:8000}"
    exec python3 run.py --http-port "$TZ_HTTP_PORT" --ws-port "$TZ_WS_PORT" --host "$TZ_HTTP_HOST"
  ) >>"$LOG" 2>&1 &
  echo $! >/tmp/three-zone.pid
}

started=0

if [[ -f "$ROOT/three-zone-mvp/run.py" ]]; then
  maybe_export_cloudflare_live_rail
  if ready "http://127.0.0.1:8000/api/health"; then
    if [[ "${TZ_LIVE_MEDIA_PROVIDER:-${TZ_MEDIA_PROVIDER:-}}" == "cloudflare" ]]; then
      current_provider="$(three_zone_media_provider)"
      if [[ "$current_provider" != "cloudflare" ]]; then
        echo "cloud-agent-start: restarting Three-Zone onto Cloudflare live rail (was ${current_provider:-unknown})"
        stop_three_zone
        start_three_zone
      else
        echo "cloud-agent-start: Three-Zone already healthy on Cloudflare"
      fi
    else
      echo "cloud-agent-start: Three-Zone already healthy"
    fi
  else
    start_three_zone
  fi
  wait_for "http://127.0.0.1:8000/api/health" "Three-Zone"
  started=1
fi

if [[ -f "$ROOT/apps/control-plane/manage.py" ]]; then
  if ready "http://127.0.0.1:8100/healthz"; then
    echo "cloud-agent-start: Moten control plane already healthy"
  else
    (
      cd "$ROOT/apps/control-plane"
      export HOST="${HOST:-0.0.0.0}"
      export PORT="${PORT:-8100}"
      exec python3 manage.py serve
    ) >>"$LOG" 2>&1 &
    echo $! >/tmp/moten-control-plane.pid
  fi
  wait_for "http://127.0.0.1:8100/healthz" "Moten control plane"
  started=1
fi

if [[ "$started" -eq 0 ]]; then
  echo "cloud-agent-start: no known app in this checkout" >&2
  exit 1
fi
echo "cloud-agent-start: ok"
