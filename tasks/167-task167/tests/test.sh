#!/usr/bin/env bash
# Runner contract: APP=/app; agent deliverables are in /app/final.
set -u
TESTS_DIR="${TESTS:-$(cd "$(dirname "$0")" && pwd)}"
LOGS_DIR="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS_DIR"
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json"
tmp="$LOGS_DIR/.verification.json.tmp"
python3 "$TESTS_DIR/verify.py" "${APP:-/app}/final" >"$tmp"
rc=$?
python3 - "$tmp" "$LOGS_DIR" "$rc" <<'PY'
import json, pathlib, sys
p, logs, rc = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
try: v=json.loads(p.read_text())
except Exception as e: v={"overall":"ENV_INVALID","infra_error":f"invalid verifier JSON: {e}"}; rc=2
s=v.get("overall",v.get("status"))
if rc==2 or s in {"ENV_INVALID","INFRA_ERROR","ERROR","ENVIRONMENT_ERROR"}: v["overall"]="ENV_INVALID"; v.pop("reward",None); rc=2
elif rc==1 or s in {"FAIL","FAILED"}: v["overall"]="FAIL"; v["reward"]=0.0; rc=1
elif rc==0 and s in {"PASS","OK","SUCCESS"}: v["overall"]="PASS"; v["reward"]=1.0
else: v={"overall":"ENV_INVALID","infra_error":f"inconsistent verifier status={s}, rc={rc}"}; rc=2
(logs/"verification.json").write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n")
if rc!=2: (logs/"reward.txt").write_text("1.0\n" if rc==0 else "0.0\n")
print(json.dumps(v,ensure_ascii=False,indent=2)); sys.exit(rc)
PY
rc=$?
rm -f "$tmp"
exit "$rc"
