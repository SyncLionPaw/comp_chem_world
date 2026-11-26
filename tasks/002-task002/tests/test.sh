#!/usr/bin/env bash
set -uo pipefail

APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
TESTS="${TESTS:-/tests}"
export APP LOGS TESTS
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/reward.json"
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
    # REVIEW_REQUIRED: pending scientific review is not a scored model failure.
    printf '{"review_required": 1}\n' > "$LOGS/reward.json"
    exit 0
    ;;
  *)
    # Infrastructure errors: leave reward unset so Harbor treats this as infra.
    echo "Case 02 verifier infrastructure failure (exit $status); no reward" >&2
    exit 2
    ;;
esac
