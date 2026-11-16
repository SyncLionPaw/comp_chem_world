#!/usr/bin/env bash
set -uo pipefail
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
export APP TESTS LOGS
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" "$LOGS/verdict.json"
trap 'rc=$?; if [ "$rc" -ne 0 ] && [ ! -f "$LOGS/verification.json" ]; then printf "{\"status\":\"INFRA_ERROR\",\"errors\":[\"grading entrypoint failed\"]}\n" > "$LOGS/verification.json"; rm -f "$LOGS/reward.txt"; fi' EXIT
/opt/netfluids/bin/python "$TESTS/verify.py" --grade

status=$?
# A scientific rejection is a scored result; infrastructure errors have no reward.
if [ "$status" -eq 1 ] && [ "$(cat "$LOGS/reward.txt" 2>/dev/null)" = "0" ]; then
    exit 0
fi
exit "$status"
