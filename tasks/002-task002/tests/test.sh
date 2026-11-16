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
python "$TESTS/verify.py"
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
    rm -f "$LOGS/reward.txt"
    exit 11
    ;;
  *)
    rm -f "$LOGS/reward.txt"
    echo "Case 02 verifier infrastructure failure (exit $status); no reward emitted" >&2
    exit "$status"
    ;;
esac
