#!/usr/bin/env bash
set -eu
APP=${APP:-/app}
TESTS=${TESTS:-/tests}
LOGS=${LOGS:-/logs/verifier}
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" "$LOGS/verifier-exit-code.txt"
set +e
python3 "$TESTS/verify.py" "$APP" --assets "${CASE_ASSETS:-/app/assets}" --logs "$LOGS"
verifier_rc=$?
set -e
printf '%s\n' "$verifier_rc" > "$LOGS/verifier-exit-code.txt"
if [ -f "$LOGS/verification.json" ]; then
  status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", ""))' "$LOGS/verification.json" 2>/dev/null || true)"
  case "$status" in
    PASS)
      [ "$verifier_rc" -eq 0 ] || exit 2
      printf '1\n' > "$LOGS/reward.txt"
      exit 0
      ;;
    FAIL)
      [ "$verifier_rc" -eq 1 ] || exit 2
      printf '0\n' > "$LOGS/reward.txt"
      exit 0
      ;;
    *) rm -f "$LOGS/reward.txt"; exit 2 ;;
  esac
fi
exit 2
