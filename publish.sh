#!/usr/bin/env bash
set -euo pipefail
TESTED_SHA="532fb6f8f445a88d28f07e7eb49afcc63e065b2a"
TARGET_BRANCH="copilot/fix-audit-chain-atomicity-rebuild"
FRESH_DIR="/tmp/three-zone-production-proof"
EXPECTED_BUNDLE_SHA="e5da23f1a7563f298e637d030fa0056dea1f3d89bad240576cb1eefd35d58339"
# ==========================================================
# OPTIONAL:
# If this machine does NOT already contain TESTED_SHA,
# set BUNDLE_PATH to the verified bundle:
#
# export BUNDLE_PATH="/path/to/audit-chain-atomicity-rebuild.bundle"
# ==========================================================
echo "=================================================="
echo "THREE-ZONE EXACT-SNAPSHOT PUBLICATION"
echo "=================================================="
# ----------------------------------------------------------
# 1. VERIFY REPOSITORY + AUTH
# ----------------------------------------------------------
git rev-parse --is-inside-work-tree >/dev/null
echo "Repository: $(pwd)"
echo "Current branch: $(git branch --show-current || true)"
echo "Current HEAD: $(git rev-parse HEAD)"
ORIGIN_URL="$(git remote get-url origin)"
echo "Origin: $ORIGIN_URL"
case "$ORIGIN_URL" in
  *bigdre816/3-Zone-Sports-*)
    echo "PASS: expected repository."
    ;;
  *)
    echo "FAIL: wrong repository."
    exit 10
    ;;
esac
echo
git status --short
echo
gh auth status || true
# ----------------------------------------------------------
# 2. LOCATE OR IMPORT EXACT TESTED COMMIT
# ----------------------------------------------------------
echo
echo "=================================================="
echo "LOCATING EXACT TESTED COMMIT"
echo "=================================================="
if git cat-file -e "${TESTED_SHA}^{commit}" 2>/dev/null; then
    echo "PASS: exact tested commit already exists locally."
else
    echo "Exact tested commit not present locally."
    if [[ -z "${BUNDLE_PATH:-}" ]]; then
        echo
        echo "BLOCKED."
        echo "Set BUNDLE_PATH to the verified bundle:"
        echo
        echo 'export BUNDLE_PATH="/path/to/audit-chain-atomicity-rebuild.bundle"'
        echo
        echo "Then run this script again."
        exit 20
    fi
    if [[ ! -f "$BUNDLE_PATH" ]]; then
        echo "FAIL: bundle not found:"
        echo "$BUNDLE_PATH"
        exit 21
    fi
    echo
    echo "Checking bundle SHA256..."
    ACTUAL_BUNDLE_SHA="$(
        sha256sum "$BUNDLE_PATH" |
        awk '{print $1}'
    )"
    echo "Actual:"
    echo "$ACTUAL_BUNDLE_SHA"
    echo "Expected:"
    echo "$EXPECTED_BUNDLE_SHA"
    if [[ "$ACTUAL_BUNDLE_SHA" != "$EXPECTED_BUNDLE_SHA" ]]; then
        echo
        echo "FAIL: bundle SHA256 mismatch."
        exit 22
    fi
    echo "PASS: bundle SHA256 verified."
    echo
    echo "Verifying Git bundle..."
    git bundle verify "$BUNDLE_PATH"
    echo
    echo "Bundle refs:"
    git bundle list-heads "$BUNDLE_PATH"
    BUNDLE_REF="$(
        git bundle list-heads "$BUNDLE_PATH" |
        awk -v sha="$TESTED_SHA" '$1 == sha {print $2; exit}'
    )"
    if [[ -z "$BUNDLE_REF" ]]; then
        echo
        echo "FAIL: bundle does not advertise tested SHA:"
        echo "$TESTED_SHA"
        exit 23
    fi
    echo
    echo "Importing exact tested object:"
    echo "$BUNDLE_REF"
    git fetch "$BUNDLE_PATH" "$BUNDLE_REF"
fi
# ----------------------------------------------------------
# 3. PROVE EXACT OBJECT EXISTS
# ----------------------------------------------------------
echo
echo "=================================================="
echo "VERIFYING EXACT OBJECT"
echo "=================================================="
OBJECT_TYPE="$(git cat-file -t "$TESTED_SHA")"
if [[ "$OBJECT_TYPE" != "commit" ]]; then
    echo "FAIL: object is not a commit."
    exit 30
fi
echo "PASS:"
echo "$TESTED_SHA"
echo
git show --stat --oneline "$TESTED_SHA"
# ----------------------------------------------------------
# 4. VERIFY FAST-FORWARD IF BRANCH EXISTS
# ----------------------------------------------------------
echo
echo "=================================================="
echo "CHECKING REMOTE BRANCH"
echo "=================================================="
REMOTE_BEFORE="$(
    git ls-remote origin \
        "refs/heads/${TARGET_BRANCH}" |
    awk '{print $1}'
)"
if [[ -n "$REMOTE_BEFORE" ]]; then
    echo "Remote currently:"
    echo "$REMOTE_BEFORE"
    git fetch origin \
        "refs/heads/${TARGET_BRANCH}:refs/remotes/origin/${TARGET_BRANCH}"
    if ! git merge-base --is-ancestor \
        "$REMOTE_BEFORE" \
        "$TESTED_SHA"
    then
        echo
        echo "FAIL: push would not be fast-forward."
        echo "NO FORCE PUSH WILL BE USED."
        exit 40
    fi
    echo "PASS: fast-forward."
else
    echo "Target branch does not exist yet."
    echo "It will be created at the tested SHA."
fi
# ----------------------------------------------------------
# 5. RECHECK DESTINATION IMMEDIATELY BEFORE PUSH
# ----------------------------------------------------------
ORIGIN_URL="$(git remote get-url origin)"
case "$ORIGIN_URL" in
  *bigdre816/3-Zone-Sports-*)
    echo "PASS: publication destination verified."
    ;;
  *)
    echo "FAIL: origin changed or is incorrect."
    exit 41
    ;;
esac
# ----------------------------------------------------------
# 6. PUSH EXACT TESTED SHA
# ----------------------------------------------------------
echo
echo "=================================================="
echo "PUBLISHING EXACT TESTED SHA"
echo "=================================================="
git push origin \
    "${TESTED_SHA}:refs/heads/${TARGET_BRANCH}"
# ----------------------------------------------------------
# 7. VERIFY REMOTE SHA
# ----------------------------------------------------------
echo
echo "=================================================="
echo "VERIFYING REMOTE"
echo "=================================================="
REMOTE_AFTER="$(
    git ls-remote origin \
        "refs/heads/${TARGET_BRANCH}" |
    awk '{print $1}'
)"
echo "Remote SHA:"
echo "$REMOTE_AFTER"
if [[ "$REMOTE_AFTER" != "$TESTED_SHA" ]]; then
    echo
    echo "FAIL: remote SHA does not equal tested SHA."
    exit 50
fi
echo
echo "PASS: exact tested SHA is remotely durable."
# ----------------------------------------------------------
# 8. FRESH CLONE
# ----------------------------------------------------------
echo
echo "=================================================="
echo "FRESH CLONE PROOF"
echo "=================================================="
rm -rf "$FRESH_DIR"
git clone \
    "$(git remote get-url origin)" \
    "$FRESH_DIR"
cd "$FRESH_DIR"
git fetch origin "$TARGET_BRANCH"
git checkout --detach \
    "origin/${TARGET_BRANCH}"
FRESH_SHA="$(git rev-parse HEAD)"
echo "Fresh clone SHA:"
echo "$FRESH_SHA"
if [[ "$FRESH_SHA" != "$TESTED_SHA" ]]; then
    echo
    echo "FAIL: fresh clone SHA mismatch."
    exit 60
fi
if [[ "$(git cat-file -t "$TESTED_SHA")" != "commit" ]]; then
    echo
    echo "FAIL: exact commit missing from fresh clone."
    exit 61
fi
echo
echo "PASS: fresh clone contains exact tested commit."
# ----------------------------------------------------------
# 9. THREE-ZONE TESTS
# ----------------------------------------------------------
echo
echo "=================================================="
echo "RUNNING THREE-ZONE TESTS"
echo "=================================================="
cd "$FRESH_DIR/three-zone-mvp"
python -m unittest -q tests.test_control_plane
python -m unittest -q tests.test_portal
python -m pytest -q
echo
echo "THREE-ZONE: PASS"
# ----------------------------------------------------------
# 10. MOTEN TESTS
# ----------------------------------------------------------
echo
echo "=================================================="
echo "RUNNING MOTEN TESTS"
echo "=================================================="
cd "$FRESH_DIR/apps/control-plane"
python -m pytest -q \
    tests/test_invariants.py \
    tests/test_evidence_chain.py
python -m pytest -q
echo
echo "MOTEN: PASS"
# ----------------------------------------------------------
# 11. ONCHAIN AUDIT TESTS
# ----------------------------------------------------------
echo
echo "=================================================="
echo "RUNNING ONCHAIN AUDIT TESTS"
echo "=================================================="
cd "$FRESH_DIR"
python -m pytest -q tests/test_onchain_audit.py
echo
echo "ONCHAIN AUDIT: PASS"
# ----------------------------------------------------------
# DONE
# ----------------------------------------------------------
echo
echo "=================================================="
echo "PUBLICATION COMPLETE"
echo "=================================================="
echo
echo "TESTED SHA:"
echo "$TESTED_SHA"
echo
echo "REMOTE BRANCH:"
echo "$TARGET_BRANCH"
echo
echo "REMOTE SHA:"
echo "$REMOTE_AFTER"
echo
echo "FRESH CLONE SHA:"
echo "$FRESH_SHA"
echo
echo "Remote exact SHA: PASS"
echo "Fresh clone exact SHA: PASS"
echo "Three-Zone tests: PASS"
echo "Moten tests: PASS"
echo "Onchain audit tests: PASS"
echo
echo "REMEDIATION SNAPSHOT:"
echo "REMOTELY RECOVERABLE + FRESH-CLONE VERIFIED"
echo
echo "NEXT:"
echo "MERGE THIS EXACT REMEDIATION."
echo "THEN CONTINUE POSTGRESQL + MOTEN + RENDER DEPLOYMENT."
