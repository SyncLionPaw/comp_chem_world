#!/usr/bin/env bash
set -uo pipefail

APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
TESTS="${TESTS:-/tests}"
export APP LOGS TESTS
mkdir -p "$LOGS" || exit 2
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" || exit 2

set +e
"${PYTHON:-python3}" "$TESTS/verify.py"
verifier_rc=$?
set -e

if [ ! -f "$LOGS/verification.json" ] || [ -L "$LOGS/verification.json" ]; then
  rm -f "$LOGS/reward.txt"
  echo "verifier did not emit a safe structured report" >&2
  exit 2
fi

decision="$("${PYTHON:-python3}" -I -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", "INVALID"))' "$LOGS/verification.json" 2>/dev/null)" || decision="INVALID"
case "$verifier_rc:$decision" in
  0:PASS)
    expected=1
    ;;
  1:FAIL)
    expected=0
    ;;
  *)
    rm -f "$LOGS/reward.txt"
    echo "verifier exit/status mismatch; no reward emitted" >&2
    exit 2
    ;;
esac

actual="$("${PYTHON:-python3}" -I -c 'import math,sys; s=open(sys.argv[1], encoding="utf-8").read().strip(); x=float(s); print(int(x) if math.isfinite(x) and x in (0,1) else "INVALID")' "$LOGS/reward.txt" 2>/dev/null)" || actual="INVALID"
if [ "$actual" != "$expected" ]; then
  rm -f "$LOGS/reward.txt"
  echo "verifier reward/status mismatch; no reward emitted" >&2
  exit 2
fi
# Harbor requires a successful verifier process; reward.txt records the score.
exit 0
