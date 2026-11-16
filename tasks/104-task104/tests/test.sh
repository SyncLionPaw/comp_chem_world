#!/bin/bash
set -u
: "${APP:=/app}"
: "${TESTS:=/tests}"
: "${LOGS:=/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
python3 "$TESTS/verify.py" --json "$APP/final" > "$LOGS/verification.json"
rc=$?
python3 - "$LOGS" "$rc" <<'PY'
import json, sys
from pathlib import Path
logs = Path(sys.argv[1])
rc = int(sys.argv[2])
path = logs / "verification.json"
reward = logs / "reward.txt"
try:
    report = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    reward.unlink(missing_ok=True)
    sys.exit(2)
if not isinstance(report, dict) or "reward" in report:
    reward.unlink(missing_ok=True)
    sys.exit(2)
overall = str(report.get("overall", ""))
status = str(report.get("status", ""))
if overall != status:
    reward.unlink(missing_ok=True)
    sys.exit(2)
if overall == "PASS" and rc == 0:
    reward.write_text("1\n", encoding="utf-8")
    report["reward"] = 1
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.exit(0)
if overall == "REVIEW_REQUIRED" and rc == 0:
    reward.unlink(missing_ok=True)
    sys.exit(0)
if overall == "FAIL" and rc == 1:
    reward.write_text("0\n", encoding="utf-8")
    report["reward"] = 0
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.exit(1)
if overall == "ERROR" and rc == 2:
    reward.unlink(missing_ok=True)
    sys.exit(2)
reward.unlink(missing_ok=True)
sys.exit(2)
PY
