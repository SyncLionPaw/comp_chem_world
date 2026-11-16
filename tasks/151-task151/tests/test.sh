#!/usr/bin/env bash
set -u
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
set +e
python3 "$TESTS/verify.py" "$APP"
rc=$?
set -e
python3 - "$LOGS/verification.json" "$LOGS/reward.txt" "$rc" <<'PY'
import json, pathlib, sys
rp,wp,rc=pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]),int(sys.argv[3])
def invalid(reason):
 wp.unlink(missing_ok=True)
 rp.parent.mkdir(parents=True,exist_ok=True)
 rp.write_text(json.dumps({'status':'ENV_INVALID','reason':reason},sort_keys=True)+'\n')
 raise SystemExit(2)
try:
 report=json.loads(rp.read_text(encoding='utf-8'))
 reward=wp.read_text(encoding='utf-8').strip() if wp.exists() else None
except (OSError,UnicodeError,json.JSONDecodeError): invalid('verifier output is missing or invalid JSON')
if not isinstance(report,dict):invalid('verifier report must be an object')
status=report.get('status'); value=report.get('reward')
valid=(status=='PASS' and rc==0 and type(value)is int and value==1 and reward=='1') or (status=='FAIL' and rc==1 and type(value)is int and value==0 and reward=='0') or (status=='ENV_INVALID' and rc==2 and 'reward' not in report and reward is None)
if not valid:invalid('status, exit code and reward protocol disagree')
raise SystemExit(rc)
PY
