#!/usr/bin/env bash
set -u
APP="${APP:-/app}"
TESTS="${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
raw="$LOGS/.h2o-verifier-output.json"
python3 "$TESTS/verify.py" --app-dir "$APP" --tests-dir "$TESTS" >"$raw" 2>&1
rc=$?
python3 - "$raw" "$LOGS" "$rc" <<'PY'
import json, pathlib, sys
raw, logs, rc = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
try:
    payload = json.loads(raw.read_text(encoding="utf-8"))
except Exception as exc:
    payload = {"status": "ERROR", "message": f"verifier emitted invalid JSON: {exc}", "reward": None}
    rc = 2
status = str(payload.get("status", "")).upper()
if status == "PASS" and rc == 0 and payload.get("reward") == 1:
    code, reward = 0, "1\n"
elif status == "FAIL" and rc == 1 and payload.get("reward") == 0:
    code, reward = 1, "0\n"
elif status == "ERROR" and rc == 2 and payload.get("reward") is None:
    code, reward = 2, None
else:
    code, reward = 2, None
    payload = {"status": "ERROR", "message": f"status/exit/reward mismatch: status={status!r}, rc={rc}", "reward": None}
(logs / "verification.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if reward is None:
    (logs / "reward.txt").unlink(missing_ok=True)
else:
    (logs / "reward.txt").write_text(reward, encoding="ascii")
print(json.dumps(payload, ensure_ascii=False))
raise SystemExit(code)
PY
exit $?
