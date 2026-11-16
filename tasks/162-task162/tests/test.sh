#!/usr/bin/env bash
set -u
export APP="${APP:-/app}"
export TESTS="${TESTS:-/tests}"
export LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
raw="$LOGS/.case-01-verifier-output.txt"
python3 "$TESTS/verify.py" "$APP" --public-input-root /app/inputs/databases --reference-file "$TESTS/refs.json" >"$raw" 2>&1
rc=$?
python3 - "$raw" "$LOGS" "$rc" "case-01" <<'PY'
import json, pathlib, sys
raw, logs, rc, case = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
message = raw.read_text(encoding="utf-8", errors="replace")
if rc == 0 and "PASS:" in message:
    status, reward, code = "PASS", 1.0, 0
elif rc == 1 and "FAIL:" in message:
    status, reward, code = "FAIL", 0.0, 1
else:
    status, reward, code = "ERROR", None, 2
payload = {"case_id": case, "status": status, "reward": reward, "message": message[-12000:]}
(logs / "verification.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if reward is None:
    (logs / "reward.txt").unlink(missing_ok=True)
else:
    (logs / "reward.txt").write_text(f"{reward:g}\n", encoding="ascii")
print(json.dumps(payload, ensure_ascii=False))
raise SystemExit(code)
PY
exit $?
