#!/usr/bin/env bash
# Isolated fixture validation for forbid_direct_ai_providers.sh (Y1a / P1-T0).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER="${SCRIPT_DIR}/forbid_direct_ai_providers.sh"
FIX="${SCRIPT_DIR}/fixtures"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/tz-forbid-XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

run_case() {
  local name="$1"
  local expect="$2" # pass|fail
  local root="$3"
  set +e
  out="$("$SCANNER" "$root" 2>&1)"
  rc=$?
  set -e
  if [[ "$expect" == "pass" && "$rc" -eq 0 ]]; then
    echo "PASS: $name"
    pass=$((pass + 1))
  elif [[ "$expect" == "fail" && "$rc" -ne 0 ]]; then
    echo "PASS: $name (scanner failed as required)"
    pass=$((pass + 1))
  else
    echo "FAIL: $name (expected $expect, rc=$rc)"
    echo "$out" | sed 's/^/  | /'
    fail=$((fail + 1))
  fi
}

# 1) Clean product code
mkdir -p "$TMP/clean/three-zone-mvp/backend"
cp "$FIX/clean_product/ok_feature.py" "$TMP/clean/three-zone-mvp/backend/ok_feature.py"
run_case "clean product code" pass "$TMP/clean"

# 2) Forbidden direct import
mkdir -p "$TMP/bad/three-zone-mvp/backend"
cp "$FIX/forbidden_direct/bad_feature.py" "$TMP/bad/three-zone-mvp/backend/bad_feature.py"
run_case "forbidden direct import" fail "$TMP/bad"

# 3) Gateway provider adapter exception (path under threezone_ai/providers/)
mkdir -p "$TMP/okprov/three-zone-mvp/threezone_ai/providers"
cp "$FIX/gateway_provider_adapter/fake_adapter.py" \
  "$TMP/okprov/three-zone-mvp/threezone_ai/providers/fake_adapter.py"
# Also include a clean product file so the tree is realistic
mkdir -p "$TMP/okprov/three-zone-mvp/backend"
cp "$FIX/clean_product/ok_feature.py" "$TMP/okprov/three-zone-mvp/backend/ok_feature.py"
run_case "gateway provider adapter" pass "$TMP/okprov"

# 4) Unrelated providers/ directory must still fail
mkdir -p "$TMP/other/three-zone-mvp/services/providers"
cp "$FIX/unrelated_providers_dir/providers/not_gateway.py" \
  "$TMP/other/three-zone-mvp/services/providers/not_gateway.py"
run_case "unrelated providers directory" fail "$TMP/other"

echo "---"
echo "fixture summary: $pass passed, $fail failed"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
