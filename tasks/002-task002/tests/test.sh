#!/usr/bin/env bash
set -uo pipefail

APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
TESTS="${TESTS:-/tests}"
export APP LOGS TESTS
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt"
rm -f "$LOGS/verification.json" "$LOGS/report.json" "$LOGS/verdict.json" "$LOGS/case02-check.json"

set +e
python3 "$TESTS/verify.py"
status=$?
set -e

case "$status" in
  0)
    printf '1\n' > "$LOGS/reward.txt"
    exit 0
    ;;
  10)
    printf '0\n' > "$LOGS/reward.txt"
    exit 0
    ;;
  11)
    # REVIEW_REQUIRED: emit 0 so Harbor records a score instead of RewardFileNotFoundError.
    printf '0
' > "$LOGS/reward.txt"
    exit 0
    ;;
  *)
    # Infrastructure errors still emit 0 for truthful eval accounting.
    printf '0
' > "$LOGS/reward.txt"
    echo "Case 02 verifier infrastructure failure (exit $status); reward=0" >&2
    exit 0
    ;;
esac
