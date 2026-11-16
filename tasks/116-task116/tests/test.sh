#!/usr/bin/env bash
set -u
: "${APP:?APP must point to the task application directory}"
: "${LOGS:?LOGS must point to /logs/verifier}"
: "${TESTS:?TESTS must point to /tests}"
mkdir -p "$LOGS/verifier"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" "$LOGS/reward.json"
python3 - "$APP" "$LOGS" <<'PYCODE'
import hashlib, json, math, os, subprocess, sys
from pathlib import Path
app, logs = Path(sys.argv[1]), Path(sys.argv[2])
tests = Path(os.environ["TESTS"])
logs.mkdir(parents=True, exist_ok=True)
verifier = tests / "verify.py"
assets = app / "environment" / "assets"
cmd = [sys.executable, str(verifier), "--assets", str(assets), "--submission", str(app)]
proc = None
try:
    proc = subprocess.run(cmd, cwd=tests, capture_output=True, text=True, check=False)
    raw = proc.stdout
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("verifier JSON root must be an object")
    except Exception as exc:
        raise RuntimeError(f"verifier stdout is not one strict JSON object: {exc}") from exc
    status = payload.get("status")
    reward = payload.get("reward")
    if status == "PASS":
        valid = proc.returncode == 0 and type(reward) in (int, float) and math.isfinite(reward) and reward == 1
    elif status == "FAIL":
        valid = proc.returncode == 1 and type(reward) in (int, float) and math.isfinite(reward) and reward == 0
    elif status == "ERROR":
        valid = proc.returncode == 2 and ("reward" not in payload or payload.get("reward") is None)
    else:
        valid = False
    if not valid:
        raise RuntimeError(f"unexpected verifier outcome status={status!r} reward={reward!r} rc={proc.returncode}")
    payload["returncode"] = proc.returncode
    payload["stdout_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    payload["stderr"] = proc.stderr[-4000:]
    payload["runtime_wrapper"] = "strict-json-v1"
    (logs / "verification.json").write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if status in ("PASS", "FAIL"):
        (logs / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
    else:
        (logs / "reward.txt").unlink(missing_ok=True)
    sys.exit(proc.returncode)
except Exception as exc:
    error = {"status":"ERROR", "error":str(exc), "runtime_wrapper":"strict-json-v1"}
    if proc is not None:
        error["verifier_returncode"] = proc.returncode
        error["verifier_stderr"] = proc.stderr[-4000:]
        error["stdout_sha256"] = hashlib.sha256(proc.stdout.encode()).hexdigest()
    (logs / "verification.json").write_text(json.dumps(error, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (logs / "reward.txt").unlink(missing_ok=True)
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(2)
PYCODE
