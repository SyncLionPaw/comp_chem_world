#!/bin/bash
set -euo pipefail
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
export BENCH_LOGS="$LOGS"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
set +e
python3 "$TESTS/verify.py" "$APP"
status=$?
set -e
if [[ ! -s "$LOGS/verification.json" ]]; then
  rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
  echo "ERROR L0: verifier did not produce a structured scientific verdict" >&2
  exit 2
fi
if [[ "$status" -gt 1 ]]; then
  rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
  echo "ERROR L0: verifier exited unexpectedly ($status)" >&2
  exit 2
fi
exit "$status"
