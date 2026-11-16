#!/usr/bin/env bash
set -euo pipefail
TESTS_DIR="${TESTS:-/tests}"
LOGS_DIR="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS_DIR"
set +e
python3 -B "$TESTS_DIR/verify.py" --test-output >"$LOGS_DIR/verification.json" 2>"$LOGS_DIR/verification.stderr"
status=$?
set -e
case "$status" in
  0)
    printf '1\n' >"$LOGS_DIR/reward.txt"
    ;;
  1)
    printf '0\n' >"$LOGS_DIR/reward.txt"
    ;;
  *)
    exit 2
    ;;
esac
