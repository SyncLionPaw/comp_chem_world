#!/usr/bin/env bash
set -eu
: "${APP:=/app}"
export APP
: "${TESTS:=/tests}"
export TESTS
: "${LOGS:=/logs/verifier}"
export LOGS
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
set +e
python3 "$TESTS/verify.py"
verifier_rc=$?
set -e
if [ -f "$LOGS/verification.json" ]; then
  status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", ""))' "$LOGS/verification.json" 2>/dev/null || true)"
  case "$status" in
    PASS) printf '1\n' > "$LOGS/reward.txt" ;;
    FAIL) printf '0\n' > "$LOGS/reward.txt" ;;
    *) rm -f "$LOGS/reward.txt" ;;
  esac
fi
exit "$verifier_rc"
