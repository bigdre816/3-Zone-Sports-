#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap. Works for both repo layouts:
#   - main: three-zone-mvp/ (Sports Access member site + /ops)
#   - Moten Phase 1 branches: apps/control-plane/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

installed=0
if [[ -f three-zone-mvp/requirements.txt ]]; then
  python3 -m pip install --break-system-packages -r three-zone-mvp/requirements.txt
  installed=1
fi
if [[ -f apps/control-plane/requirements.txt ]]; then
  python3 -m pip install --break-system-packages -r apps/control-plane/requirements.txt
  installed=1
fi
if [[ "$installed" -eq 0 ]]; then
  echo "cloud-agent-install: no requirements.txt found (expected three-zone-mvp/ or apps/control-plane/)" >&2
  exit 1
fi
python3 --version
echo "cloud-agent-install: ok"
