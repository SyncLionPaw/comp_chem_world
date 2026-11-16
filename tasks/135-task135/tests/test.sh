#!/usr/bin/env bash
set -uo pipefail
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
final="$APP"
if [ "$APP" = /app ]; then final=/app/final; fi
APP="$final" python3 "$TESTS/verify.py" >"$LOGS/scorer.stdout" 2>"$LOGS/scorer.stderr"
rc=$?
python3 - "$rc" "$LOGS" <<'PYWRAP'
import json,sys
from pathlib import Path
rc=int(sys.argv[1]); d=Path(sys.argv[2])
try:
 obj=json.loads((d/'scorer.stdout').read_text())
 if not isinstance(obj,dict): raise ValueError('verifier output must be one JSON object')
 expected={0:'PASS',1:'FAIL'}.get(rc)
 if expected:
  if obj.get('status')!=expected or obj.get('reward')!={0:1,1:0}[rc]: raise ValueError('status/reward and exit code disagree')
 elif rc==2:
  if obj.get('status') not in {'ERROR','ENVIRONMENT_ERROR','ENV_ERROR','INFRA_ERROR'} or obj.get('reward') is not None: raise ValueError('infra error must have no reward')
  obj['original_verifier_status']=obj['status']; obj['status']='ENV_INVALID'
 else: raise ValueError('unexpected verifier exit code')
except Exception as exc:
 rc=2; obj={'status':'ENV_INVALID','original_verifier_status':None,'reason':str(exc)}
(d/'verification.json').write_text(json.dumps(obj,allow_nan=False,sort_keys=True)+'\n')
if rc in (0,1): (d/'reward.txt').write_text(str({0:1,1:0}[rc])+'\n')
sys.exit(rc)
PYWRAP
exit $?
