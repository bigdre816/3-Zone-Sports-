#!/usr/bin/env bash
# CI referee: product code must not call cloud/local AI SDKs except via threezone_ai.providers (gateway-owned).
set -euo pipefail
ROOT="${1:-.}"
# Scan app code; allow the gateway package providers/ and tests/
FAIL=0
while IFS= read -r -d '' f; do
  case "$f" in
    */threezone_ai/providers/*|*/threezone_ai/tests/*|*/threezone-ai-lanes/*) continue ;;
  esac
  if grep -nE 'import (groq|openai|google\.generativeai|ollama)|from (groq|openai)|api\.groq\.com|generativelanguage\.googleapis|workers\.ai/|OLLAMA_HOST|ChatGroq|CloudflareAI' "$f" 2>/dev/null; then
    echo "FORBIDDEN direct AI provider usage in: $f"
    FAIL=1
  fi
done < <(find "$ROOT/three-zone-mvp" -type f \( -name '*.py' -o -name '*.js' -o -name '*.ts' \) ! -path '*/threezone_ai/providers/*' ! -path '*/.venv/*' -print0 2>/dev/null || true)

if [[ "$FAIL" -ne 0 ]]; then
  echo "CI FAIL: call AI only through threezone_ai.gateway.run"
  exit 1
fi
echo "OK: no direct AI provider imports outside gateway providers/"
