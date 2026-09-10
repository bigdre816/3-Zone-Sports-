#!/bin/sh
set -e
mkdir -p /data /app/data
PORT="${PORT:-${TZ_HTTP_PORT:-8000}}"
exec python run.py --host 0.0.0.0 --http-port "$PORT"
