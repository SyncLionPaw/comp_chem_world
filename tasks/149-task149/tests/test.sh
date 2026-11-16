#!/usr/bin/env bash
set -uo pipefail
export APP="${APP:-/app}" TESTS="${TESTS:-/tests}" LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/reward.json" "$LOGS/reward.json.tmp"
set +e
python3 "$TESTS/verify.py"
result=$?
set -e
exit "$result"
