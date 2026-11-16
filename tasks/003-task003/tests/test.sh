#!/bin/sh
# APP contains final/ and public assets; TESTS contains the v6 verifier and refs.json.
set -u
APP_DIR=${APP:-/app}
TESTS_DIR=${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
LOGS_DIR=${LOGS:-/logs/verifier}
mkdir -p "$LOGS_DIR" || exit 2
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json"

if python3 "$TESTS_DIR/verify.py" \
  --submission "$APP_DIR" \
  --assets "$APP_DIR/assets" \
  --refs "$TESTS_DIR/refs.json" \
  > "$LOGS_DIR/verification.json" 2> "$LOGS_DIR/verifier.stderr"; then
  verifier_rc=0
else
  verifier_rc=$?
fi
cat "$LOGS_DIR/verification.json" 2>/dev/null || {
  rm -f "$LOGS_DIR/reward.txt"
  cat "$LOGS_DIR/verifier.stderr" >&2
  exit 2
}
python3 - "$LOGS_DIR/verification.json" "$verifier_rc" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
rc = int(sys.argv[2])
try:
    report = json.loads(path.read_text(encoding="utf-8"))
    status = report.get("status")
except Exception:
    raise SystemExit(2)
expected = {0: {"PASS"}, 1: {"FAIL"}, 2: {"INFRA_ERROR", "REVIEW_REQUIRED"}}
if status not in expected.get(rc, set()):
    raise SystemExit(2)
PY
status_check=$?
if [ "$status_check" -ne 0 ]; then
  rm -f "$LOGS_DIR/reward.txt"
  exit 2
fi
case "$verifier_rc" in
  0) printf '1\n' > "$LOGS_DIR/reward.txt" || exit 2; exit 0 ;;
  1) printf '0\n' > "$LOGS_DIR/reward.txt" || exit 2; exit 0 ;;
  *) rm -f "$LOGS_DIR/reward.txt"; exit 2 ;;
esac
