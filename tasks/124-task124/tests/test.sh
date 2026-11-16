#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
APP=/app TESTS=/tests LOGS=/logs/verifier /tests/original-test.sh > /logs/verifier/original.stdout 2>&1
native_rc=$?
printf '%s\n' "$native_rc" > /logs/verifier/native-exit-code.txt
cat /logs/verifier/original.stdout
if python3 - "$native_rc" /logs/verifier/verification.json /logs/verifier/reward.txt <<'PYVERIFY'
import json, pathlib, sys
rc=int(sys.argv[1]); result_path=pathlib.Path(sys.argv[2]); reward_path=pathlib.Path(sys.argv[3])
try:
    result=json.loads(result_path.read_text())
    reward=float(reward_path.read_text().strip())
except Exception:
    raise SystemExit(1)
if rc == 0 and result.get('status') == 'PASS' and reward == 1.0:
    raise SystemExit(0)
if rc == 1 and result.get('status') == 'FAIL' and reward == 0.0:
    raise SystemExit(0)
raise SystemExit(1)
PYVERIFY
then
  exit 0
fi
if [ "$native_rc" -ne 0 ]; then exit "$native_rc"; fi
exit 2
