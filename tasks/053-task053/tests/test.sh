#!/bin/sh
set -u
APP=/app
ASSETS=/app/environment/assets
TESTS=/tests
LOGS=/logs/verifier
PATH=/usr/bin:/bin
export PATH
export APP ASSETS TESTS LOGS
# Harbor uploads /tests into this isolated verifier container as a writable tree.
# Reject links, then restore the trusted scorer boundary before reading payloads.
test -d "$TESTS" && test ! -L "$TESTS" || exit 2
if find "$TESTS" -type l -print -quit | grep -q .; then exit 2; fi
chown root:root "$TESTS" || exit 2
find "$TESTS" -type d -exec chown root:root {} + -exec chmod 0700 {} + || exit 2
find "$TESTS" -type f -exec chown root:root {} + -exec chmod 0400 {} + || exit 2
mkdir -p "$LOGS" || exit 2
/usr/bin/python3 -I - "$LOGS" <<'PYWRITE' || exit 2
import json, os, pathlib, secrets, subprocess, sys, sysconfig
logs = pathlib.Path(sys.argv[1])
if logs.is_symlink() or not logs.is_dir():
    raise SystemExit("worker write probe requires a real verifier log directory")
os.chown(logs, 0, 0)
os.chmod(logs, 0o700)
uid = 200000000 + secrets.randbelow(100000000)
gid = 300000000 + secrets.randbelow(100000000)
probe = r'''import errno,json,os,pathlib,secrets,sys,sysconfig
s={x.split(":",1)[0]:x.split(":",1)[1].strip() for x in open("/proc/self/status") if ":" in x}
token=secrets.token_hex(12)
paths=[("/usr/local/bin", ".ccw-write-probe-"+token), (sysconfig.get_paths()["purelib"], ".ccw-write-probe-"+token), ("/tests", ".ccw-write-probe-"+token), (sys.argv[1], ".ccw-write-probe-"+token)]
def denied(parent,name):
 p=pathlib.Path(parent)
 if not p.is_dir(): return False
 try:
  fd=os.open(str(p/name),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd);(p/name).unlink();return False
 except OSError as e: return e.errno in (errno.EACCES,errno.EPERM,errno.EROFS)
checks={parent:denied(parent,name) for parent,name in paths}
print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),"groups":os.getgroups(),"nnp":s.get("NoNewPrivs"),"caps":s.get("CapEff"),"denied":checks},sort_keys=True))
'''
cmd=["/usr/bin/setpriv",f"--reuid={uid}",f"--regid={gid}","--clear-groups","--bounding-set=-all","--inh-caps=-all","--ambient-caps=-all","--no-new-privs","/usr/bin/python3","-I","-c",probe,str(logs)]
r=subprocess.run(cmd,cwd="/tmp",env={"PATH":"/usr/bin:/bin","HOME":"/nonexistent"},capture_output=True,text=True,timeout=15,close_fds=True)
try: row=json.loads(r.stdout.strip())
except Exception as e: raise SystemExit(f"worker write probe output invalid: {e}; rc={r.returncode}; stderr={r.stderr[:1000]}")
expected={"/usr/local/bin":True,sysconfig.get_paths()["purelib"]:True,"/tests":True,str(logs):True}
if r.returncode or row.get("uid")!=uid or row.get("gid")!=gid or row.get("groups")!=[] or row.get("nnp")!="1" or row.get("caps")!="0000000000000000" or row.get("denied")!=expected:
    raise SystemExit("low-privilege worker could write trusted/system path or lacked isolation: "+json.dumps(row,sort_keys=True))
(logs/"worker-write-probe.json").write_text(json.dumps({"schema":"bench08-worker-write-probe/v1",**row,"exit_code":r.returncode},sort_keys=True,indent=2)+"\n",encoding="utf-8")
PYWRITE
rm -f "$LOGS/reward.txt" "$LOGS/reward.json" "$LOGS/verification.json" "$LOGS/verdict.json" "$LOGS/auto-result.json" "$LOGS/transport-stdout.txt" "$LOGS/native-reward.txt"
/usr/bin/python3 -I - "$LOGS/runtime-mounts.json" <<'PYMOUNT'
import json, os, pathlib, stat, sys
mounts = []
for line in pathlib.Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
    left, right = line.split(" - ", 1)
    fields = left.split()
    point = fields[4].replace("\\040", " ")
    tail = right.split()
    if point in ("/", "/app", "/tests", "/logs", "/tmp"):
        mounts.append({"target": point, "mount_options": fields[5].split(","), "filesystem": tail[0], "source": tail[1]})
paths = {}
for name in ("/", "/app", "/tests", "/logs", "/tmp"):
    try:
        st = os.stat(name, follow_symlinks=False)
        paths[name] = {"readonly": bool(os.statvfs(name).f_flag & getattr(os, "ST_RDONLY", 1)), "mode": oct(stat.S_IMODE(st.st_mode)), "uid": st.st_uid, "gid": st.st_gid}
    except OSError as exc:
        paths[name] = {"error": type(exc).__name__}
pathlib.Path(sys.argv[1]).write_text(json.dumps({"mounts": mounts, "paths": paths}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
PYMOUNT
/usr/bin/python3 -I -B "$TESTS/verify.py" >"$LOGS/transport-stdout.txt" 2>&1
status=$?
cat "$LOGS/transport-stdout.txt" || { rm -f "$LOGS/reward.txt" "$LOGS/reward.json"; exit 2; }
if [ -f "$LOGS/reward.txt" ]; then
  cp "$LOGS/reward.txt" "$LOGS/native-reward.txt" || { rm -f "$LOGS/reward.txt" "$LOGS/reward.json"; exit 2; }
fi
rm -f "$LOGS/reward.txt" "$LOGS/reward.json"
/usr/bin/python3 -I - "$LOGS" "$status" <<'PY'
import json, math, os, pathlib, sys
from decimal import Decimal, InvalidOperation
logs = pathlib.Path(sys.argv[1])
exit_code = int(sys.argv[2])
reward_path = logs / "reward.txt"
json_reward_path = logs / "reward.json"
try:
    report = json.loads((logs / "verification.json").read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("verification report must be an object")
    native_reward = (logs / "native-reward.txt").read_text(encoding="ascii").strip()
    reward = Decimal(native_reward)
    reported = report.get("reward")
    if isinstance(reported, bool) or not isinstance(reported, (int, float)) or reported not in (0, 1) or not math.isfinite(reported):
        raise ValueError("report reward must be finite numeric")
    if not reward.is_finite():
        raise ValueError("reward file must be finite numeric")
except (OSError, UnicodeError, ValueError, InvalidOperation, OverflowError):
    reward_path.unlink(missing_ok=True)
    json_reward_path.unlink(missing_ok=True)
    raise SystemExit(2)
if exit_code == 0 and report.get("status") == "PASS" and reported == 1.0 and reward == Decimal("1"):
    tmp = logs / ".reward.tmp"
    tmp.write_text("1\n", encoding="ascii")
    json_reward_path.unlink(missing_ok=True)
    os.replace(tmp, reward_path)
    raise SystemExit(0)
if exit_code == 1 and report.get("status") == "FAIL" and reported == 0 and reward == Decimal("0"):
    tmp = logs / ".reward.tmp"
    tmp.write_text("0\n", encoding="ascii")
    json_reward_path.unlink(missing_ok=True)
    os.replace(tmp, reward_path)
    raise SystemExit(0)
reward_path.unlink(missing_ok=True)
json_reward_path.unlink(missing_ok=True)
raise SystemExit(2)
PY
