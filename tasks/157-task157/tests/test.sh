#!/usr/bin/env bash
# Harbor scoring entry for task 157 (fail-closed).
# The scientific scorer below is unchanged; this entrypoint only runs it,
# normalizes its exit code into the verification report, and decides the reward.
# PASS -> reward 1; scientific FAIL -> reward 0; an infrastructure error or a
# self-inconsistent report removes the reward and exits 2, so the runner records
# verifier_error instead of a false PASS.
set -uo pipefail
APP="${APP:-/app}"
TESTS="${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS" || exit 2
rm -f "$LOGS/reward.txt" "$LOGS/reward.json" "$LOGS/verification.json" \
      "$LOGS/scorer.stdout" "$LOGS/scorer.stderr" \
      "$LOGS/harbor-error.json" "$LOGS/harbor-transport.json"

# 1. Run the scientific scorer and normalize its exit code into a report.
python "$TESTS/verify.py" "$APP" >"$LOGS/scorer.stdout" 2>"$LOGS/scorer.stderr"
NATIVE_RC=$?
python3 - "$NATIVE_RC" "$LOGS" <<'PY'
import json,sys
from pathlib import Path
rc=int(sys.argv[1]); d=Path(sys.argv[2]); out=(d/'scorer.stdout').read_text(errors='replace'); err=(d/'scorer.stderr').read_text(errors='replace')
status={0:'PASS',1:'FAIL',2:'ERROR'}.get(rc)
reward={0:1,1:0}.get(rc)
if status is None:
 status='ERROR'; reward=None
detail=out.strip() or err.strip()
# If the underlying verifier emits JSON, enforce its own status/reward contract too.
for line in reversed(out.splitlines()):
 try: obj=json.loads(line)
 except Exception: continue
 if not isinstance(obj,dict) or 'status' not in obj: continue
 inner=str(obj['status']).upper(); inner_reward=obj.get('reward')
 expected=('PASS' if rc==0 else 'FAIL' if rc==1 else None)
 allowed_error={'ERROR','ENVIRONMENT_ERROR','ENV_ERROR','INFRA_ERROR'}
 if expected and (inner!=expected or inner_reward!=reward):
  status='ERROR'; reward=None; detail='verifier JSON status/reward disagrees with process exit code'
 elif not expected and (inner not in allowed_error or inner_reward is not None):
  status='ERROR'; reward=None; detail='environment-error JSON must have no reward'
 break
report={'status':status,'detail':detail}
if reward is not None:
 report['reward']=reward; (d/'reward.txt').write_text(f'{reward}\n')
(d/'verification.json').write_text(json.dumps(report,sort_keys=True)+'\n')
PY

# 2. Reward gate: only a self-consistent PASS/1/0 or FAIL/0/1 earns a score.
python3 - "$NATIVE_RC" "$LOGS" <<'PY'
import json,sys
from pathlib import Path
native_rc=int(sys.argv[1]); logs=Path(sys.argv[2])
try:
 raw=json.loads((logs/'verification.json').read_text())
 status=raw.get('status',raw.get('overall'))
 # A Python crash can return 1 too; it is not a scientific FAIL.
 if native_rc==1 and 'Traceback (most recent call last):' in str(raw.get('detail','')):
  raise ValueError('underlying verifier crashed before scientific classification')
 reward_file=logs/'reward.txt'
 reward=float(reward_file.read_text()) if reward_file.is_file() else None
 (logs/'harbor-transport.json').write_text(json.dumps({'native_exit_code':native_rc,'native_status':status,'reward':reward})+'\n')
 if native_rc in (0,1) and (status,reward,native_rc) in (('PASS',1.0,0),('FAIL',0.0,1)):
  sys.exit(0)
 raise ValueError('underlying verifier reported an infrastructure error or inconsistent reward')
except Exception as exc:
 for name in ('reward.txt','reward.json'):
  (logs/name).unlink(missing_ok=True)
 (logs/'harbor-error.json').write_text(json.dumps({'status':'ERROR','reward':None,'error':str(exc)})+'\n')
 print(str(exc),file=sys.stderr)
 raise SystemExit(2)
PY
