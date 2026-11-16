#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${APP:-/app}"
TESTS="${TESTS:-$HERE}"
LOGS="${LOGS:-/logs/verifier}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/reward.json" "$LOGS/verification.json" "$LOGS/returncode.txt" "$LOGS/contract-error.txt"
set +e
"$PYTHON_BIN" -B -I "$HERE/verify.py" --app-dir "$APP" --tests-dir "$TESTS" --logs-dir "$LOGS" >"$LOGS/stdout.raw" 2>"$LOGS/stderr.raw"
rc=$?
set -e
check="$($PYTHON_BIN -I - "$LOGS/verification.json" "$rc" <<'PY'
import json,sys
try:
    d=json.load(open(sys.argv[1],encoding='utf-8'));rc=int(sys.argv[2])
except Exception:
    raise SystemExit(2)
expected={0:{'EVIDENCE_REVIEW','NOT_EVALUATED'},1:{'NOT_EVALUATED'},2:{'NOT_EVALUATED','EVIDENCE_REVIEW'}}.get(rc)
reward=d.get('reward','missing')
artifact_score=d.get('artifact_score','missing')
reviewed=(d.get('status') in {'PASS','FAIL'} and d.get('overall_science_status')==d.get('status')
          and reward==(1 if d.get('status')=='PASS' else 0) and d.get('human_review_required') is False)
pending=(d.get('status')=='REVIEW_REQUIRED' and d.get('overall_science_status')=='INCONCLUSIVE'
         and reward is None and isinstance(d.get('review_request'),dict))
if expected is None or d.get('candidate_status') not in expected or d.get('score_kind')!='open_research_evidence':
    raise SystemExit(2)
if rc==2:
    if d.get('status')=='ENV_INVALID' and reward is None:
        raise SystemExit(0)
    trusted_error=(d.get('candidate_status')=='NOT_EVALUATED' and d.get('local_check')=='ERROR' and d.get('status')=='ERROR' and reward is None)
    if not trusted_error: raise SystemExit(2)
if rc==1:
    if d.get('status')!='REJECTED' or reward!=0 or d.get('candidate_status')!='NOT_EVALUATED': raise SystemExit(2)
if rc==0 and (not reviewed and not pending):
    raise SystemExit(2)
if rc==0:
    if not isinstance(artifact_score,(int,float)) or not (0.0<=artifact_score<=1.0) or d.get('execution_attested') is not False:
        raise SystemExit(2)
raise SystemExit(0)
PY
)" || check=ERROR
if [ "$check" != "" ]; then
  rm -f "$LOGS/reward.txt"
  printf '%s\n' 'Verifier contract mismatch; no task reward assigned' > "$LOGS/contract-error.txt"
  exit 2
fi
"$PYTHON_BIN" -I - "$LOGS/verification.json" "$LOGS/reward.txt" "$LOGS/reward.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
if type(d.get('reward')) in (int,float): open(sys.argv[2],'w',encoding='ascii').write(f"{float(d['reward']):.2f}\n")
elif d.get('status')=='REVIEW_REQUIRED': open(sys.argv[3],'w',encoding='ascii').write('{}\n')
PY
exit "$rc"
