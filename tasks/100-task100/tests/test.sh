#!/usr/bin/env bash
# Independent grader entry: only a consistent scientific verdict writes reward.
set -u
export APP="${APP:-/app}"
export TESTS="${TESTS:-/tests}"
export LOGS="${LOGS:-/logs/verifier}"
if ! mkdir -p "$LOGS" 2>/dev/null; then
  printf '%s\n' '{"schema":"case05-verification-result/v1","status":"ERROR","reward":null,"error":"verifier log directory is not writable"}'
  exit 2
fi
if ! rm -f "$LOGS/reward.txt" "$LOGS/verification.json" 2>/dev/null; then
  printf '%s\n' '{"schema":"case05-verification-result/v1","status":"ERROR","reward":null,"error":"cannot clear stale verifier outputs"}'
  exit 2
fi
python3 "$TESTS/verify.py"
verifier_rc=$?
python3 - "$LOGS" "$verifier_rc" <<'PY'
import json, math, pathlib, sys
logs = pathlib.Path(sys.argv[1])
rc = int(sys.argv[2])
report = logs / 'verification.json'
reward_file = logs / 'reward.txt'
def emit_error(message):
    result = {'schema':'case05-verification-result/v1', 'status':'ERROR', 'reward':None,
              'error':f'grader contract: {message}'}
    encoded = json.dumps(result, allow_nan=False) + '\n'
    try:
        if reward_file.exists() or reward_file.is_symlink(): reward_file.unlink()
    except OSError:
        pass
    try:
        if report.is_symlink(): report.unlink()
        report.write_text(encoded)
    except OSError:
        pass
    print(encoded, end='')
    print(f'ERROR: grader contract: {message}', file=sys.stderr)
    raise SystemExit(2)
try:
    if report.is_symlink() or not report.is_file():
        raise ValueError('verifier did not produce a regular verification.json')
    result = json.loads(report.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    status, reward = result.get('status'), result.get('reward')
    if status == 'PASS' and rc == 0 and type(reward) in (int, float) and reward == 1:
        reward_file.write_text('1\n')
        raise SystemExit(0)
    if status == 'FAIL' and rc == 1 and type(reward) in (int, float) and reward == 0:
        reward_file.write_text('0\n')
        raise SystemExit(1)
    if status == 'PARTIAL' and rc == 1 and type(reward) in (int, float) and math.isfinite(reward) and 0 < reward < 1:
        reward_file.write_text(str(reward)+'\n')
        raise SystemExit(1)
    if status == 'ERROR' and rc == 2 and reward is None:
        raise SystemExit(2)
    raise ValueError('verifier exit code, verdict and reward disagree')
except Exception as exc:
    emit_error(f'{type(exc).__name__}: {exc}')
PY
contract_rc=$?
case "$contract_rc" in
  0|1|2) ;;
  *)
    rm -f "$LOGS/reward.txt" "$LOGS/verification.json" 2>/dev/null || true
    printf '%s\n' '{"schema":"case05-verification-result/v1","status":"ERROR","reward":null,"error":"grader contract interpreter failed"}' > "$LOGS/verification.json" 2>/dev/null || true
    printf '%s\n' '{"schema":"case05-verification-result/v1","status":"ERROR","reward":null,"error":"grader contract interpreter failed"}'
    exit 2
    ;;
esac
if [[ "$contract_rc" == 2 ]]; then
  rm -f "$LOGS/reward.txt"
fi
exit "$contract_rc"
