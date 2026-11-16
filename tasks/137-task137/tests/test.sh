#!/usr/bin/env bash
set -uo pipefail
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/reward.json" "$LOGS/verification.json"
final="$APP"
if [ "$APP" = /app ]; then final=/app/final; fi
APP="$final" python3 "$TESTS/verify.py" >"$LOGS/scorer.stdout" 2>"$LOGS/scorer.stderr"
rc=$?
python3 - "$rc" "$LOGS" <<'PYWRAP'
import json, math, os, sys
from pathlib import Path
rc=int(sys.argv[1]); d=Path(sys.argv[2])
try:
 obj=json.loads((d/'scorer.stdout').read_text())
 if not isinstance(obj,dict): raise ValueError('verifier output must be one JSON object')
 if obj.get('construction_status')!='DRAFT' or obj.get('evaluation_coverage')!='PARTIAL' or obj.get('research_success')!='INCONCLUSIVE': raise ValueError('scientific result boundary fields violate the case contract')
 if rc==0:
  score=obj.get('automatic_audit_score')
  if obj.get('status')!='REVIEW_REQUIRED' or 'reward' in obj or isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=0.60: raise ValueError('review-required audit/status outside contract')
  if obj.get('scientific_review_status')!='PENDING' or obj.get('scientific_conclusion_verified') is not False: raise ValueError('scientific review must remain pending')
 elif rc==1:
  if obj.get('status')!='FAIL' or obj.get('reward')!=0: raise ValueError('submission failure must have reward zero')
 elif rc==2:
  if obj.get('status')!='ENV_ERROR' or obj.get('reward') is not None: raise ValueError('verifier failure must have no reward')
  obj['original_verifier_status']=obj['status']; obj['status']='ENV_INVALID'
 else: raise ValueError('unexpected verifier exit code')
except Exception as exc:
 rc=2; obj={'status':'ENV_INVALID','original_verifier_status':None,'exit_code':2,'reward':None,'construction_status':'DRAFT','evaluation_coverage':'PARTIAL','research_success':'INCONCLUSIVE','evaluation_error':True,'reason':str(exc)}
(d/'verification.json').write_text(json.dumps(obj,allow_nan=False,sort_keys=True)+'\n')
if rc==1: (d/'reward.txt').write_text('0\n')
if os.environ.get('BENCH20_HARBOR_AUDIT') == '1' and rc in (0,1):
 score=obj['automatic_audit_score'] if rc == 0 else 0
 (d/'reward.json').write_text(json.dumps({'automatic_audit_score':score},allow_nan=False,sort_keys=True)+'\n')
 (d/'reward.txt').write_text(f'{score:.6f}\n')
sys.exit(rc)
PYWRAP
exit $?
