#!/usr/bin/env bash
set -euo pipefail
TESTS="$(cd -- "$(dirname -- "$0")" && pwd)"
APP="${1:-${APP:-/app}}"
LOGS="${LOGS:-/logs/verifier}"
export APP TESTS LOGS
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt"
tmp="$(mktemp "$LOGS/.verify.XXXXXX")"
set +e
python3 -B "$TESTS/verify.py" "$APP" >"$tmp"
rc=$?
set -e
python3 - "$tmp" "$LOGS" "$rc" <<'PY'
import json, pathlib, sys
src, logs, rc = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
try:
    report=json.loads(src.read_text(encoding='utf-8'))
    if not isinstance(report,dict): raise ValueError('verifier report is not an object')
except Exception as exc:
    report={'status':'INFRA_ERROR','error':f'verifier emitted invalid JSON: {exc}'}
status=report.get('status')
if status in {'PASS','REVIEW_REQUIRED'} and rc != 0:
    report={'status':'INFRA_ERROR','error':f'verifier status {status} conflicts with exit code {rc}'}; status='INFRA_ERROR'
elif status == 'FAIL' and rc not in (0,1):
    report={'status':'INFRA_ERROR','error':f'verifier status FAIL conflicts with exit code {rc}'}; status='INFRA_ERROR'
elif status not in {'FAIL','PASS','REVIEW_REQUIRED','INFRA_ERROR'}:
    report={'status':'INFRA_ERROR','error':f'unsupported status: {status!r}'}; status='INFRA_ERROR'
(logs/'verification.json').write_text(json.dumps(report,ensure_ascii=False)+'\n',encoding='utf-8')
(logs/'raw-verifier.stdout.json').write_text(src.read_text(encoding='utf-8'),encoding='utf-8')
src.unlink(missing_ok=True); (logs/'reward.txt').unlink(missing_ok=True)
if status == 'PASS': (logs/'reward.txt').write_text('1\n', encoding='ascii'); code=0
elif status == 'FAIL': (logs/'reward.txt').write_text('0\n', encoding='ascii'); code=1
elif status == 'REVIEW_REQUIRED':
    (logs/'reward.txt').unlink(missing_ok=True)
    (logs/'reward.json').write_text('{"review_required": 1, "reward": null}\n', encoding='ascii'); code=0
else:
    (logs/'reward.txt').unlink(missing_ok=True)
    (logs/'reward.json').write_text('{"infra_error": 1, "reward": null}\n', encoding='ascii'); code=2
raise SystemExit(code)
PY
