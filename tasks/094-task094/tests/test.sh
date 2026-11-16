#!/bin/bash
set -euo pipefail
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
PUBLIC_LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$PUBLIC_LOGS"
chmod 700 "$PUBLIC_LOGS"
rm -f "$PUBLIC_LOGS/reward.txt" "$PUBLIC_LOGS/verification.json"
PRIVATE_ROOT="$(mktemp -d /tmp/bench14-private-verify.XXXXXX)"
trap 'rm -rf "$PRIVATE_ROOT"' EXIT
chmod 700 "$PRIVATE_ROOT"
PRIVATE_TESTS="$PRIVATE_ROOT/tests"
LOGS="$PRIVATE_ROOT/logs"
mkdir -m 700 "$PRIVATE_TESTS" "$LOGS"
cp -R "$TESTS/." "$PRIVATE_TESTS/"
chmod 700 "$PRIVATE_TESTS"
TESTS="$PRIVATE_TESTS"
export BENCH_LOGS="$LOGS"
set +e
python3 "$TESTS/verify.py" "$APP"
status=$?
set -e
if ! python3 - <<'PY'
#!/usr/bin/env python3
"""Kill and reject any unprivileged candidate left alive before score export."""
from __future__ import annotations

import glob
import os
import pwd
import signal
import time

uid = pwd.getpwnam("nobody").pw_uid

def live_candidates():
    live = []
    for entry in glob.glob("/proc/[0-9]*"):
        try:
            pid = int(entry.rsplit("/", 1)[1])
            status = open(entry + "/status", encoding="ascii").read().splitlines()
        except (OSError, ValueError):
            continue
        state = next((line.split()[1] for line in status if line.startswith("State:")), "?")
        ids_line = next((line for line in status if line.startswith("Uid:")), "")
        try:
            effective_uid = int(ids_line.split()[2])
        except (IndexError, ValueError):
            continue
        if effective_uid == uid and state != "Z":
            live.append(pid)
    return live

before = live_candidates()
for pid in before:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        print(f"cannot kill surviving nobody process {pid}")
        raise SystemExit(1)
time.sleep(0.1)
after = live_candidates()
if after:
    print(f"nobody candidate processes survived cleanup: {after}")
    raise SystemExit(1)
print(f"PASS: no live nobody candidate processes before score export (killed={before})")
PY
then
  rm -f "$PUBLIC_LOGS/reward.txt" "$PUBLIC_LOGS/verification.json"
  echo "ERROR L0: unprivileged candidate process survived before score export" >&2
  exit 2
fi
if [[ ! -s "$LOGS/verification.json" || "$status" -gt 1 ]]; then
  rm -f "$PUBLIC_LOGS/reward.txt" "$PUBLIC_LOGS/verification.json"
  echo "ERROR L0: verifier/reference failure without a structured verdict" >&2
  exit 2
fi
cp "$LOGS/reward.txt" "$PUBLIC_LOGS/reward.txt"
cp "$LOGS/verification.json" "$PUBLIC_LOGS/verification.json"
cmp -s "$LOGS/reward.txt" "$PUBLIC_LOGS/reward.txt"
cmp -s "$LOGS/verification.json" "$PUBLIC_LOGS/verification.json"
exit "$status"
