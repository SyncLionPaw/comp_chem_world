#!/usr/bin/env bash
set -u
APP="${APP:-/app}"; TESTS="${TESTS:-/tests}"; LOGS="${LOGS:-/logs/verifier}"; export APP TESTS LOGS
mkdir -p "$LOGS" || exit 2
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" "$LOGS/verdict.json"
set +e
python3 "$TESTS/verify.py" "$APP"
rc=$?
set -e
set +e
python3 - outcome "$LOGS/verification.json" "$LOGS/reward.txt" "$rc" <<'PY'
"""Independently validate verifier return code, structured outcome, and reward."""
import json, math, pathlib, sys

mode, report_name, reward_name, rc_text = sys.argv[1:]
if mode != 'outcome': raise SystemExit(2)
try:
    rc=int(rc_text); report=json.loads(pathlib.Path(report_name).read_text(encoding='utf-8'))
except (OSError,UnicodeError,ValueError,json.JSONDecodeError): raise SystemExit(2)
if not isinstance(report,dict): raise SystemExit(2)
status=report.get('status')
reward_path=pathlib.Path(reward_name)
if status=='ENV_INVALID':
    raise SystemExit(0 if rc==2 and not reward_path.exists() else 2)
try:
    raw=reward_path.read_text(encoding='utf-8'); reward=float(raw)
except (OSError,UnicodeError,ValueError): raise SystemExit(2)
if not math.isfinite(reward): raise SystemExit(2)
def score(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
if status=='PASS':
    ok=(rc==0 and all(score(report.get(k)) for k in ('earned','maximum','reward'))
        and report['earned']==report['maximum']==report['reward']==reward==1)
elif status=='FAIL':
    ok=(rc==1 and score(report.get('earned')) and score(report.get('maximum')) and score(report.get('reward'))
        and report['earned']==report['reward']==reward==0 and report['maximum']==1)
else: ok=False
raise SystemExit(0 if ok else 2)
PY
protocol_rc=$?
set -e
if [ "$protocol_rc" -ne 0 ]; then
  rm -f "$LOGS/reward.txt"
  printf '%s\n' '{"status":"ENV_INVALID","reason":"verifier outcome, structured receipt, and reward are missing or inconsistent"}' > "$LOGS/verification.json"
  exit 2
fi
exit "$rc"
