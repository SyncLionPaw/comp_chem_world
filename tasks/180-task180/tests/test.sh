#!/usr/bin/env bash
set -u
APP="${APP:-/app}"
TESTS="${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)}"
LOGS="${LOGS:-/logs/verifier}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/reward.json" "$LOGS/verification.json" "$LOGS/returncode.txt" "$LOGS/contract-error.txt"
set +e
"$PYTHON_BIN" -B -I "$TESTS/verify.py" --app-dir "$APP" --tests-dir "$TESTS" >"$LOGS/verification.json" 2>"$LOGS/stderr.raw"
rc=$?
set -e
set +e
"$PYTHON_BIN" -I - "$LOGS/verification.json" "$rc" <<'PYCONTRACT'
import json,sys
try:
    d=json.load(open(sys.argv[1],encoding='utf-8')); rc=int(sys.argv[2])
except Exception:
    raise SystemExit(2)
common=(d.get('score_kind')=='native_artifact_consistency'
        and d.get('execution_attested') is False and d.get('source_truth_verified') is False
        and d.get('human_review_required') is False)
if rc==0:
    if not common or d.get('status') not in ('PASS','PARTIAL') or d.get('local_check')!=d.get('status') or d.get('overall_science_status')!=d.get('status') or type(d.get('reward')) not in (int,float) or not 0<=d['reward']<=1:
        raise SystemExit(2)
    if d['status']=='PASS' and (d['reward']!=1.0 or d.get('scientific_success') is not True):
        raise SystemExit(2)
    if d['status']=='PARTIAL' and d.get('scientific_success') is not False:
        raise SystemExit(2)
    bands=[row.get('numeric_band') for row in d.get('same_geometry_reference_diagnostics',[])]
    score=1.0 if len(bands)==3 and all(x=='PASS' for x in bands) else (0.5 if len(bands)==3 and 'GRAY' in bands and all(x in ('PASS','GRAY') for x in bands) else 0.0)
    if d['reward']!=score or d['status']!=('PASS' if score==1.0 else 'PARTIAL'):
        raise SystemExit(2)
elif rc==1:
    if not common or d.get('status')!='REJECTED' or d.get('reward')!=0.0 or d.get('scientific_success') is not False:
        raise SystemExit(2)
elif rc==2:
    if d.get('status')!='ERROR' or d.get('reward') is not None:
        raise SystemExit(2)
else:
    raise SystemExit(2)
raise SystemExit(0)
PYCONTRACT
contract_rc=$?
set -e
if [ "$contract_rc" -ne 0 ]; then
  rm -f "$LOGS/reward.txt" "$LOGS/reward.json"
  printf '%s\n' 'Verifier result/status/reward contract mismatch; no task reward assigned' > "$LOGS/contract-error.txt"
  exit 2
fi
if [ "$rc" -lt 2 ]; then
  "$PYTHON_BIN" -I - "$LOGS/verification.json" "$LOGS/reward.txt" <<'PYREWARD'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
open(sys.argv[2],'w',encoding='utf-8').write(f"{d['reward']:.8g}\n")
PYREWARD
fi
printf '%s\n' "$rc" > "$LOGS/returncode.txt"
if [ "$rc" -eq 2 ]; then rm -f "$LOGS/reward.txt" "$LOGS/reward.json"; fi
exit "$rc"
