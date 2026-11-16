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

decision="$("${PYTHON:-python3}" -I -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); s=d.get("status"); r=d.get("reward"); ok=type(r) in (int,float); print("PASS" if s=="PASS" and ok and r==1 else ("FAIL" if s=="FAIL" and ok and r==0 else "INVALID"))' "$LOGS/verification.json" 2>/dev/null)" || decision="INVALID"
case "$verifier_rc:$decision" in
  0:PASS)
    printf '1\n' > "$LOGS/reward.txt"
    exit 0
    ;;
  1:FAIL)
    printf '0\n' > "$LOGS/reward.txt"
    # Harbor requires a successful verifier process; reward.txt records the score.
    exit 0
    ;;
esac
rm -f "$LOGS/reward.txt"
echo "verifier exit/status/reward contract mismatch; no reward emitted" >&2
exit 2
