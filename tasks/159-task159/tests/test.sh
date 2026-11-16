#!/usr/bin/env bash
# Harbor scoring entry for task 159 (fail-closed).
# The scientific scorer below is unchanged; this entrypoint only runs it and
# decides the reward from its report. PASS -> reward 1; scientific FAIL ->
# reward 0; an infrastructure error or a self-inconsistent report removes the
# reward and exits 2, so the runner records verifier_error instead of a false PASS.
set -uo pipefail
APP="${APP:-/app}"
TESTS="${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS" || exit 2
rm -f "$LOGS/reward.txt" "$LOGS/reward.json" "$LOGS/verification.json" "$LOGS/verdict.json" \
      "$LOGS/report.json" "$LOGS/scorer.stdout" "$LOGS/scorer.stderr" \
      "$LOGS/harbor-error.json" "$LOGS/harbor-transport.json" \
      "$LOGS/credential-isolation.json"

# A fresh Harbor grader uses the candidate image, but no candidate credentials.
# Only the disposable grader overlay is changed; the image and host are untouched.
if [[ ! -f /.dockerenv || -S /var/run/docker.sock || -S /run/host-services/ssh-auth.sock ]]; then
  printf '%s\n' '{"status":"ERROR","reward":null,"error":"grader credential isolation prerequisite failed"}' > "$LOGS/harbor-error.json"
  exit 2
fi
unset SSH_AUTH_SOCK SSH_AGENT_PID
if ! python3 - "$LOGS/credential-isolation.json" <<'PYSSH'
import json
import os
import stat
import sys

path = "/root/.ssh"
try:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("SSH path is not a root-owned mode-0700 directory")
    with os.scandir(path) as entries:
        if next(entries, None) is not None:
            raise ValueError("SSH directory contains residual entries")

    mounts = []
    for line in open("/proc/self/mountinfo", encoding="utf-8"):
        left, right = line.rstrip("\n").split(" - ", 1)
        fields, details = left.split(), right.split()
        mountpoint = fields[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
        if mountpoint == path:
            mounts.append((details[0], set(fields[5].split(","))))
    if len(mounts) > 1:
        raise ValueError("SSH path has ambiguous mount records")

    if mounts:
        fstype, options = mounts[0]
        if fstype != "tmpfs" or not {"rw", "noexec", "nosuid", "nodev"}.issubset(options):
            raise ValueError("SSH path is not a safely masked tmpfs")
        directory_absent = False
        directory_masked = True
    else:
        # Older grader images may expose an empty image-owned directory. Only
        # remove it when no /root bind mount could redirect the operation.
        for line in open("/proc/self/mountinfo", encoding="utf-8"):
            left, _ = line.rstrip("\n").split(" - ", 1)
            fields = left.split()
            mountpoint = fields[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
            if mountpoint == "/root":
                raise ValueError("/root is a mount; refusing to alter SSH path")
        os.rmdir(path)
        directory_absent = True
        directory_masked = False

    receipt = {
        "credential_directory_absent": directory_absent,
        "credential_directory_empty": True,
        "credential_directory_masked": directory_masked,
        "credential_directory_mount_type": "tmpfs" if directory_masked else None,
        "agent_socket_unset": True,
        "scope": "fresh grader overlay or isolated tmpfs",
    }
    with open(sys.argv[1], "w", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.write("\n")
except Exception as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
PYSSH
then
  printf '%s\n' '{"status":"ERROR","reward":null,"error":"grader SSH credentials could not be masked"}' > "$LOGS/harbor-error.json"
  exit 2
fi

# 1. Run the scientific scorer; it writes verification.json and reward.txt itself.
python3 "$TESTS/verify.py"
NATIVE_RC=$?

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
