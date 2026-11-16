#!/usr/bin/env bash
# Harbor verifier entry for task-154-phase-stability.
# Preserve the structured PASS/FAIL/ERROR verdict, numerical reward, and exit-code contract:
#   - executed as `bash /tests/test.sh` with APP=/app TESTS=/tests LOGS=/logs/verifier
#   - reward: single finite value in [0,1] written to $LOGS/reward.txt
#   - structured report: $LOGS/verification.json (status/reward must agree)
#   - PASS -> exit 0, FAIL (scientific) -> exit 1, environment/asset error -> exit 2
#     and no reward file may remain on an environment error.
set -u

LOGS_DIR="${LOGS:-/logs/verifier}"
APP_DIR="${APP:-/app}"
TESTS_DIR="${TESTS:-/tests}"
SUBMISSION="$APP_DIR/final/stacking.json"

mkdir -p "$LOGS_DIR" 2>/dev/null || true
# Environment errors must not leave a stale reward behind.
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json" "$LOGS_DIR/reward.json"

emit_out="$(mktemp)"
trap 'rm -f "$emit_out"' EXIT
python3 "$TESTS_DIR/verify.py" --package "$APP_DIR" --submission "$SUBMISSION" \
  >"$emit_out" 2>"$LOGS_DIR/verify.stderr"
verify_rc=$?

python3 - "$emit_out" "$LOGS_DIR" "$verify_rc" <<'PY'
import json, sys

out_path, logs_dir, rc = sys.argv[1], sys.argv[2], int(sys.argv[3])
raw = open(out_path, encoding="utf-8").read()
payload = None
try:
    payload = json.loads(raw[raw.index("{"):])
except (ValueError, TypeError):
    payload = None

status = str(payload.get("status", "")).upper() if isinstance(payload, dict) else ""
reward = payload.get("reward") if isinstance(payload, dict) else None

if status == "PASS" and reward == 1:
    exit_code = 0
elif status == "FAIL":
    exit_code = 1
    reward = 0
else:
    # ERROR (asset/environment) or an unparseable verifier outcome: no reward.
    if status not in ("ERROR",):
        payload = {"status": "ERROR",
                   "message": f"verifier exited with rc={rc} without a structured verdict"}
    payload.pop("reward", None)
    status, reward, exit_code = "ERROR", None, 2

report = dict(payload) if isinstance(payload, dict) else {"status": status}
report["status"] = status
if reward is not None:
    report["reward"] = reward
with open(f"{logs_dir}/verification.json", "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2)
if reward is not None:
    with open(f"{logs_dir}/reward.txt", "w", encoding="utf-8") as fh:
        fh.write(f"{reward}\n")
sys.exit(exit_code)
PY
protocol_rc=$?
# Surface the verifier's own stdout for the grade log.
cat "$emit_out"
exit "$protocol_rc"
