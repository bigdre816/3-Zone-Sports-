#!/bin/sh
set -e
mkdir -p /data /app/data
# Render injects PORT (typically 10000) and health-checks that port. Local
# docker/dev fall back to TZ_HTTP_PORT or 8000.
PORT="${PORT:-${TZ_HTTP_PORT:-8000}}"
echo "[three-zone] binding HTTP on 0.0.0.0:${PORT}"
exec python run.py --host 0.0.0.0 --http-port "$PORT"
