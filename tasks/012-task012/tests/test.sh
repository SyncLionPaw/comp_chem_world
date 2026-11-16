#!/bin/sh
# CompChemBench scoring entry (fail-closed).
# PASS -> reward 1; candidate FAIL -> reward 0. A tampered input surface, a
# broken grader or an invocation failure writes no reward file and exits 2, so
# the runner records verifier_error instead of a false PASS.
set -u
APP_DIR=${APP:-/app}
TESTS_DIR=${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
LOGS_DIR=${LOGS:-/logs/verifier}
mkdir -p "$LOGS_DIR" || exit 2
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json"

if python3 "$TESTS_DIR/verify.py" \
  --app-dir "$APP_DIR" \
  --tests-dir "$TESTS_DIR" \
  --final-dir "$APP_DIR/final" \
  --report "$LOGS_DIR/verification.json" \
  >"$LOGS_DIR/verifier.stdout" 2>&1; then verifier_rc=0; else verifier_rc=$?; fi
cat "$LOGS_DIR/verification.json" 2>/dev/null || true

status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' \
  "$LOGS_DIR/verification.json" 2>/dev/null) || {
  echo "grader produced no readable report (exit $verifier_rc)" >&2
  cat "$LOGS_DIR/verifier.stdout" >&2
  exit 2
}

case "$status:$verifier_rc" in
  PASS:0) printf '1\n' > "$LOGS_DIR/reward.txt" || exit 2; exit 0 ;;
  FAIL:1) printf '0\n' > "$LOGS_DIR/reward.txt" || exit 2; exit 0 ;;
  *)
    echo "no reward: status=$status rc=$verifier_rc" >&2
    cat "$LOGS_DIR/verifier.stdout" >&2
    exit 2
    ;;
esac
