#!/usr/bin/env bash
set -eu
APP="${APP:-/app}"; TESTS="${TESTS:-/tests}"; LOGS="${LOGS:-/logs/verifier}"; export APP TESTS LOGS
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
exec python3 "$TESTS/verify.py"
