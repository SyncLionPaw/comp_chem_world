#!/bin/sh
set -u
APP=${APP:-/app}
TESTS=${TESTS:-/tests}
LOGS=${LOGS:-/logs/verifier}
export APP TESTS LOGS
mkdir -p "$LOGS" || exit 2
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
python3 "$TESTS/verify.py" > "$LOGS/verifier.out" 2>&1
rc=$?
cat "$LOGS/verifier.out"
if [ "$rc" -gt 1 ]; then rm -f "$LOGS/reward.txt"; fi
exit "$rc"
