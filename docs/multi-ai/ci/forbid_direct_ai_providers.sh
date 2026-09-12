#!/usr/bin/env bash
# CI referee: product code must not call cloud/local AI SDKs except via
# threezone_ai.providers (gateway-owned).
#
# Detection limitations (documented — not a complete security boundary):
# - Static pattern match only (import/URL/SDK name heuristics).
# - Does not catch dynamic import(), __import__, httpx to arbitrary hosts,
#   subprocess wrappers, or renamed vendored SDKs.
# - Does not prove runtime isolation or credential separation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# docs/multi-ai/ci → repo root is three levels up
DEFAULT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
ROOT="${1:-$DEFAULT_ROOT}"

# If caller passed ".", resolve against cwd but prefer finding three-zone-mvp
if [[ ! -d "${ROOT}/three-zone-mvp" ]]; then
  echo "CI FAIL: three-zone-mvp not found under ROOT=${ROOT}" >&2
  echo "Pass the repository root explicitly, or run from a checkout that contains it." >&2
  exit 2
fi

FAIL=0
while IFS= read -r -d '' f; do
  case "$f" in
    */threezone_ai/providers/*|*/threezone_ai/tests/*|*/threezone-ai-lanes/*) continue ;;
    */docs/multi-ai/ci/fixtures/*) continue ;;
  esac
  if grep -nE 'import (groq|openai|google\.generativeai|ollama)|from (groq|openai)|api\.groq\.com|generativelanguage\.googleapis|workers\.ai/|OLLAMA_HOST|ChatGroq|CloudflareAI' "$f" 2>/dev/null; then
    echo "FORBIDDEN direct AI provider usage in: $f"
    FAIL=1
  fi
done < <(find "$ROOT/three-zone-mvp" -type f \( -name '*.py' -o -name '*.js' -o -name '*.ts' \) \
  ! -path '*/threezone_ai/providers/*' \
  ! -path '*/.venv/*' \
  ! -path '*/docs/multi-ai/ci/fixtures/*' \
  -print0 2>/dev/null || true)

if [[ "$FAIL" -ne 0 ]]; then
  echo "CI FAIL: call AI only through threezone_ai.gateway.run"
  exit 1
fi
echo "OK: no direct AI provider imports outside gateway providers/"
