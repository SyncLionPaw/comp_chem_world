#!/bin/sh
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR=${APP:-/app}
TESTS_DIR=${TESTS:-$HERE}
LOGS=${LOGS:-/logs/verifier}
mkdir -p "$LOGS" || exit 2
rm -f "$LOGS/reward.txt"
python3 "$TESTS_DIR/verify.py" --submission "$APP_DIR/final" --assets "$APP_DIR/assets" --refs "$TESTS_DIR/refs.json" \
  >"$LOGS/verification.json" 2>&1
status=$?
# The generic runner accepts FAIL/PASS, while the Case01 checker uses the
# more specific SCIENTIFIC_FAIL label. Normalize only the transport label;
# preserve the checker detail and its reward semantics.
if [ "$status" -eq 1 ]; then
  python3 - "$LOGS/verification.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    report = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(0)
if isinstance(report, dict) and report.get("status") == "SCIENTIFIC_FAIL":
    report["status"] = "FAIL"
    path.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
PY
fi
cat "$LOGS/verification.json" || exit 2
case "$status" in
  0)
    result=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", ""))' "$LOGS/verification.json" 2>/dev/null) || exit 2
    if [ "$result" = "PASS" ]; then
      printf '1\n' > "$LOGS/reward.txt" || exit 2
      exit 0
    fi
    # Static diagnostics and incomplete review states are never official rewards.
    exit 2
    ;;
  1)
    result=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", ""))' "$LOGS/verification.json" 2>/dev/null) || exit 2
    if [ "$result" = "FAIL" ]; then
      printf '0\n' > "$LOGS/reward.txt" || exit 2
      exit 0
    fi
    exit 2
    ;;
  11)
    # Unsupported named QS methods require review and never receive a reward.
    exit 11
    ;;
  *)
    exit 2
    ;;
esac
