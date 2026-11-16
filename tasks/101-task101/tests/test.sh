#!/usr/bin/env bash
set -u
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" "$LOGS/verdict.json" \
  "$LOGS/result.json" "$LOGS/error.json"
REFS_SHA256='53246eeddd104e7805b150614078a6c5488ebb230dc0397a3da7574dd82799d6'
if ! python3 - "$TESTS/refs.json" "$REFS_SHA256" <<'PY'
import hashlib, pathlib, sys
p=pathlib.Path(sys.argv[1])
raise SystemExit(0 if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[2] else 1)
PY
then
  printf '{"status":"ERROR","reason":"pinned refs.json is missing or changed"}\n' > "$LOGS/verification.json"
  printf 'ERROR: pinned refs.json is missing or changed\n' >&2
  exit 2
fi
set +e
python3 "$TESTS/verify.py"
rc=$?
set -e
report="$LOGS/verification.json"
if [[ ! -f "$report" || -L "$report" ]]; then
  rm -f "$LOGS/reward.txt"
  if [[ -L "$report" ]]; then rm -f "$report"; fi
  printf '{"status":"ERROR","reason":"verifier did not produce a regular verification.json"}\n' > "$report"
  printf 'ERROR: verifier did not produce a regular verification.json\n' >&2
  exit 2
fi
set +e
python3 - "$report" "$rc" "$LOGS/reward.txt" <<'PY'
import json, math, os, pathlib, sys
report_path, rc_text, reward_path = sys.argv[1:]
rc = int(rc_text)
try:
    doc = json.loads(pathlib.Path(report_path).read_text())
    status = doc.get("status")
    reward = doc.get("reward")
except Exception as exc:
    try:
        pathlib.Path(report_path).write_text(json.dumps({"status":"ERROR", "reason":f"invalid verifier JSON: {type(exc).__name__}"})+"\n")
    except Exception:
        pass
    raise SystemExit(2)
if status == "PASS" and rc == 0 and reward == 1 and not isinstance(reward, bool):
    pathlib.Path(reward_path).write_text("1\n")
    raise SystemExit(0)
if status == "FAIL" and rc == 1 and reward == 0 and not isinstance(reward, bool):
    pathlib.Path(reward_path).write_text("0\n")
    raise SystemExit(1)
if status == "ERROR" and rc == 2 and "reward" not in doc:
    try: pathlib.Path(reward_path).unlink()
    except FileNotFoundError: pass
    raise SystemExit(2)
try: pathlib.Path(reward_path).unlink()
except FileNotFoundError: pass
pathlib.Path(report_path).write_text(json.dumps({"status":"ERROR", "reason":"verifier exit code, report, and reward disagree"})+"\n")
print("ERROR: verifier exit code, report, and reward disagree", file=sys.stderr)
raise SystemExit(2)
PY
contract_rc=$?
set -e
if [[ "$contract_rc" -ne "$rc" ]]; then
  rm -f "$LOGS/reward.txt"
  printf 'ERROR: verifier contract validation failed\n' >&2
  exit 2
fi
case "$rc" in
  0|1) exit "$rc" ;;
  *) rm -f "$LOGS/reward.txt"; exit 2 ;;
esac
