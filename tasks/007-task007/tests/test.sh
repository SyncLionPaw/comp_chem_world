#!/usr/bin/env bash
set -u
APP=${APP:-/app}
TESTS=${TESTS:-/tests}
LOGS=${LOGS:-/logs/verifier}
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"

set +e
python3 "$TESTS/verify.py" --app "$APP" --report "$LOGS/verification.json"
runner_status=$?
set -e

if [ ! -s "$LOGS/verification.json" ]; then
  printf '%s\n' '{"schema":"case01-verification/v1","case_id":"case-01","status":"ENV_INVALID","scientific_status":"UNVERIFIED","errors":["trusted verifier produced no structured report"]}' > "$LOGS/verification.json"
  exit 2
fi

python3 - "$LOGS/verification.json" "$LOGS/reward.txt" "$runner_status" <<'PY'
import json, pathlib, sys
report_path, reward_path, runner_status = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
try:
    report = json.loads(report_path.read_text())
except Exception:
    raise SystemExit(2)
status = report.get("status")
has_reward = "reward" in report
reward = report.get("reward")
if status == "PASS" and has_reward and reward == 1.0 and runner_status == 0:
    reward_path.write_text("1\n")
    raise SystemExit(0)
if status == "FAIL" and has_reward and reward == 0.0 and runner_status == 1:
    reward_path.write_text("0\n")
    raise SystemExit(1)
if status == "ENV_INVALID" and not has_reward and runner_status == 2:
    raise SystemExit(2)
# Any disagreement between the structured outcome and trusted runner exit is
# an infrastructure protocol error, and therefore never awards a score.
raise SystemExit(2)
PY
