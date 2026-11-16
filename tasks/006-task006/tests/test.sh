#!/bin/sh
set -u
APP=${APP:-/app}
TESTS=${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
LOGS=${LOGS:-/logs/verifier}
export APP TESTS LOGS
mkdir -p "$LOGS" || exit 2
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
python3 "$TESTS/verify.py" > "$LOGS/verifier.stdout" 2>&1
rc=$?
cat "$LOGS/verifier.stdout"
if [ "$rc" -gt 1 ]; then rm -f "$LOGS/reward.txt"; fi
exit "$rc"
