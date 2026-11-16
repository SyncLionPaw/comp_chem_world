#!/usr/bin/env bash
set -euo pipefail

# Standard Harbor starts the separate verifier before artifact delivery. Defer
# trusted-artifact rehydration and grading until test.sh runs after delivery.
LOG_DIR="${LOGS:-/logs/verifier}"
if [[ "${CCB_BENCH25_GUARDED:-}" != "1" ]]; then
python3 -B -I - "$LOG_DIR" <<'PY'
import os, stat, sys
path=sys.argv[1]
if os.path.islink(path): raise SystemExit('verifier log directory is redirected')
os.makedirs(path,mode=0o700,exist_ok=True)
fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
try:
    os.fchown(fd,0,0);os.fchmod(fd,0o700)
    if os.fstat(fd).st_uid!=0 or os.fstat(fd).st_mode&0o077:
        raise SystemExit('verifier log directory is not root-only')
    failures=[]
    for name in ('reward.txt','reward.json','verification.json','verdict.json'):
        try: entry=os.stat(name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError: continue
        try:
            if stat.S_ISDIR(entry.st_mode): os.rmdir(name,dir_fd=fd)
            else: os.unlink(name,dir_fd=fd)
        except OSError as exc: failures.append(f'{name}: {exc}')
    if failures: raise SystemExit('cannot clear all stale verifier records: '+'; '.join(failures))
finally: os.close(fd)
PY
  exec python3 -B -I /opt/bench25/entrypoint.py grade -- /bin/bash "$0" "$@"
fi

TEST_DIR="${TESTS:-/tests}"
APP_DIR="${APP:-/app}"
PYTHON="${CASE04_PYTHON:-python3}"
VERIFY="$TEST_DIR/verify.py"
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"
rm -f "$LOG_DIR/reward.txt" "$LOG_DIR/reward.json" "$LOG_DIR/verification.json" "$LOG_DIR/verdict.json"
stdout_file="$(mktemp "$LOG_DIR/.case04-verify-stdout.XXXXXX")"
stderr_file="$(mktemp "$LOG_DIR/.case04-verify-stderr.XXXXXX")"
report_tmp="$(mktemp "$LOG_DIR/.case04-verification.XXXXXX")"
trap 'rm -f "$stdout_file" "$stderr_file" "$report_tmp"' EXIT

set +e
"$PYTHON" -B -I "$VERIFY" "$APP_DIR" >"$stdout_file" 2>"$stderr_file"
verify_rc=$?
set -e

case "$verify_rc" in
  0) status="PASS"; reward="1"; message="case04 bounded probe audit passed" ;;
  1) status="FAIL"; reward="0"; message="candidate failed case04 probe audit" ;;
  2) status="ENV_INVALID"; reward=""; message="trusted case04 execution context is unavailable or invalid" ;;
  *) status="ENV_INVALID"; reward=""; message="verifier exited unexpectedly"; verify_rc=2 ;;
esac

"$PYTHON" -B - "$report_tmp" "$status" "$verify_rc" "$reward" "$message" "$stdout_file" "$stderr_file" <<'PY'
import json
import sys
from pathlib import Path

target, status, exit_code, reward, message, stdout_path, stderr_path = sys.argv[1:]
details = "\n".join(part for part in (
    Path(stdout_path).read_text(encoding="utf-8", errors="replace").strip(),
    Path(stderr_path).read_text(encoding="utf-8", errors="replace").strip(),
) if part)
record = {
    "schema": "compchembench-scorer-report/v1",
    "case_id": "case-04",
    "status": status,
    "exit_code": int(exit_code),
    "message": message + (": " + details[-4000:] if details else ""),
}
if reward:
    record["reward"] = int(reward)
Path(target).write_text(json.dumps(record, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
PY
chmod 600 "$report_tmp"
mv "$report_tmp" "$LOG_DIR/verification.json"
if [[ -n "$reward" ]]; then
  reward_tmp="$(mktemp "$LOG_DIR/.case04-reward.XXXXXX")"
  printf '%s\n' "$reward" >"$reward_tmp"
  chmod 600 "$reward_tmp"
  mv "$reward_tmp" "$LOG_DIR/reward.txt"
fi

exit "$verify_rc"
