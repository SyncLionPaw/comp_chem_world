#!/usr/bin/env bash
set -u
APP="${APP:-/app}"
TESTS="${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)}"
LOGS="${LOGS:-/logs/verifier}"
ASSETS="${ASSETS:-/environment/assets/public-inputs-v2}"
PYTHON="${PYTHON_BIN:-python3}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
set +e
"$PYTHON" "$TESTS/verify.py" --app-dir "$APP" --assets-dir "$ASSETS" >"$LOGS/verification.json" 2>"$LOGS/stderr.raw"
rc=$?
set -e
if ! python3 - "$LOGS/verification.json" "$rc" <<'PY'
import json,sys
p,rc=sys.argv[1],int(sys.argv[2])
try:
 d=json.load(open(p,encoding='utf-8'))
 expected={0:('PASS',1),1:('FAIL',0),2:('ERROR',None)}[rc]
 ok=d.get('status')==expected[0] and d.get('reward')==expected[1]
 if expected[0]!='ERROR': ok=ok and d.get('task_status')==('COMPLETED_VALIDATION' if rc==0 else 'FAILED_REQUIREMENTS')
 else: ok=ok and d.get('task_status')=='NOT_EVALUATED'
except Exception: ok=False
if not ok:
 open(p,'w',encoding='utf-8').write(json.dumps({'status':'ERROR','task_status':'NOT_EVALUATED','science_status':'INCONCLUSIVE','reward':None,'message':'verifier JSON/status/exit/reward contract mismatch'})+'\n')
 raise SystemExit(1)
PY
then
  rm -f "$LOGS/reward.txt"
  exit 2
fi
if [ "$rc" -eq 0 ]; then printf '1\n' > "$LOGS/reward.txt"; elif [ "$rc" -eq 1 ]; then printf '0\n' > "$LOGS/reward.txt"; elif [ "$rc" -eq 2 ]; then rm -f "$LOGS/reward.txt"; else exit 2; fi
exit "$rc"
