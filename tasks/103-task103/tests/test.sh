#!/bin/bash
set -u
: "${APP:=/app}"
: "${TESTS:=/tests}"
: "${LOGS:=/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
python3 "$TESTS/verify.py" --json "$APP/final" > "$LOGS/verify-stdout.json"
rc=$?
python3 - "$LOGS" "$rc" <<'PY'
import json, sys
from pathlib import Path
logs = Path(sys.argv[1])
rc = int(sys.argv[2])
raw = logs / "verify-stdout.json"
try:
    report = json.loads(raw.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    sys.exit(2)
if not isinstance(report, dict):
    sys.exit(2)
passed = report.get("pass") is True
if rc == 0 and passed:
    overall, reward, exit_code = "PASS", 1, 0
elif rc == 1 and not passed:
    overall, reward, exit_code = "FAIL", 0, 1
else:
    report["status"] = report["overall"] = "ERROR"
    report.pop("reward", None)
    (logs / "verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    raw.unlink(missing_ok=True)
    sys.exit(2)
report["status"] = report["overall"] = overall
report["reward"] = reward
(logs / "verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
(logs / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
raw.unlink(missing_ok=True)
sys.exit(exit_code)
PY
