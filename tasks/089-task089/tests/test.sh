#!/bin/bash
set -euo pipefail
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
SOLUTION="${SOLUTION:-/solution}"
PUBLIC_LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$PUBLIC_LOGS"
rm -f "$PUBLIC_LOGS/reward.txt" "$PUBLIC_LOGS/verification.json" \
  "$PUBLIC_LOGS/task90-objective-receipt.json" "$PUBLIC_LOGS/task90-candidate-report.json"

PRIVATE_ROOT="$(mktemp -d /tmp/task90-private-verify.XXXXXX)"
trap 'rm -rf "$PRIVATE_ROOT"' EXIT
chmod 700 "$PRIVATE_ROOT"
PRIVATE_TESTS="$PRIVATE_ROOT/tests"
PRIVATE_LOGS="$PRIVATE_ROOT/logs"
mkdir -m 700 "$PRIVATE_TESTS" "$PRIVATE_LOGS"
cp -R "$TESTS/." "$PRIVATE_TESTS/"
chmod 700 "$PRIVATE_TESTS"
export BENCH_LOGS="$PRIVATE_LOGS"
export BENCH_PUBLIC_TESTS="$TESTS"
export BENCH_SOLUTION_DIR="$SOLUTION"

set +e
python3 "$PRIVATE_TESTS/verify.py" "$APP"
status=$?
set -e
if [[ ! -s "$PRIVATE_LOGS/verification.json" || "$status" -gt 1 ]]; then
  rm -f "$PUBLIC_LOGS/reward.txt" "$PUBLIC_LOGS/verification.json"
  echo "ERROR L0: verifier did not produce a structured verdict" >&2
  exit 2
fi
cp "$PRIVATE_LOGS/reward.txt" "$PUBLIC_LOGS/reward.txt"
cp "$PRIVATE_LOGS/verification.json" "$PUBLIC_LOGS/verification.json"
chmod 600 "$PUBLIC_LOGS/reward.txt" "$PUBLIC_LOGS/verification.json"
if [[ -s "$PRIVATE_LOGS/task90-objective-receipt.json" ]]; then
  cp "$PRIVATE_LOGS/task90-objective-receipt.json" "$PUBLIC_LOGS/task90-objective-receipt.json"
  cp "$PRIVATE_LOGS/task90-candidate-report.json" "$PUBLIC_LOGS/task90-candidate-report.json"
  chmod 600 "$PUBLIC_LOGS/task90-objective-receipt.json" "$PUBLIC_LOGS/task90-candidate-report.json"
fi
exit "$status"
