#!/bin/sh
# PASS -> reward 1; candidate FAIL -> reward 0. Unsupported, protected-input
# errors, grader errors, and invocation failures create no reward file.
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export BLIS_NUM_THREADS=1
set -u
APP_DIR=${APP:-/app}
TESTS_DIR=${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
LOGS_DIR=${LOGS:-/logs/verifier}
mkdir -p "$LOGS_DIR" || exit 2
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json"

if python3 "$TESTS_DIR/verify.py"   --final-dir "$APP_DIR/final"   --runtime-dir "$LOGS_DIR/runtime"   --gold-path "$TESTS_DIR/protected/case04_answers.csv"   --report "$LOGS_DIR/verification.json"   >"$LOGS_DIR/verifier.stdout" 2>&1; then verifier_rc=0; else verifier_rc=$?; fi
python3 - "$LOGS_DIR/verification.json" "$verifier_rc" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
try:
    report = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
if int(sys.argv[2]) == 2 and report.get("status") == "UNSUPPORTED":
    report["native_status"] = "UNSUPPORTED"
    report["status"] = "REVIEW_REQUIRED"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
cat "$LOGS_DIR/verification.json" 2>/dev/null || true

if ! python3 - "$LOGS_DIR/verification.json" "$verifier_rc" <<'PY'
import json, pathlib, sys
try:
    report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(2)
rc, status = int(sys.argv[2]), report.get("status")
if rc == 0 and status == "PASS":
    print("PASS")
elif rc == 1 and status == "FAIL":
    print("FAIL")
elif rc == 2 and status == "REVIEW_REQUIRED" and report.get("native_status") == "UNSUPPORTED":
    print("REVIEW_REQUIRED")
else:
    print("UNSUPPORTED_OR_GRADER_ERROR")
    raise SystemExit(2)
PY
then
  rm -f "$LOGS_DIR/reward.txt"
  cat "$LOGS_DIR/verifier.stdout" >&2
  exit 2
fi
status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$LOGS_DIR/verification.json") || {
  rm -f "$LOGS_DIR/reward.txt"; exit 2;
}
case "$status" in
  PASS) printf '1\n' > "$LOGS_DIR/reward.txt" || exit 2; exit 0 ;;
  FAIL) printf '0\n' > "$LOGS_DIR/reward.txt" || exit 2; exit 0 ;;
  REVIEW_REQUIRED) rm -f "$LOGS_DIR/reward.txt"; exit 2 ;;
  *) rm -f "$LOGS_DIR/reward.txt"; exit 2 ;;
esac
